"""Porta do modelo de linguagem.

O agente conversa com esta interface, nunca com um SDK. Duas implementações:

* **Anthropic** — o destino. Tem cache de prompt (é o que sustenta o orçamento
  de latência de voz) e saídas estruturadas validadas por Pydantic.
* **OpenRouter** — ponte para o período sem chave da Anthropic. Sem cache: cada
  turno reprocessa o prompt de sistema inteiro.

A diferença de custo e latência entre as duas é real e está documentada em
:mod:`central_ia.integrations.llm.openrouter`. Trocar é mudar `LLM_PROVIDER`.
"""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, Field

Papel = Literal["user", "assistant", "system"]
Esforco = Literal["low", "medium", "high", "xhigh", "max"]


class OrcamentoDeTokensEstourado(RuntimeError):
    """O modelo gastou o orçamento raciocinando e não escreveu nada.

    ⚠️ **Falha real, 28/08/2026, e ela derruba o atendimento.** No turno em que
    o cliente recusa a supressão dos avisos, que é a decisão mais difícil do
    playbook, o modelo consumiu os 400 tokens pensando e devolveu conteúdo
    vazio. A conversa virou `falha_tecnica_no_atendimento` e o cliente recebeu
    uma despedida de caso registrado para um caso que não foi registrado.

    Tem exceção própria porque **é recuperável e as outras não são**: chave
    inválida ou provedor fora do ar não melhoram numa segunda tentativa; esta
    melhora, bastando pedir menos raciocínio. Quem trata é
    `agent/atendimento_real.py`.

    ⚠️ **Cobre só `finish_reason: length`.** O modelo que devolve vazio dizendo
    que terminou normalmente é `RespostaVaziaDoModelo`, abaixo.
    """


class RespostaVaziaDoModelo(RuntimeError):
    """O modelo disse que terminou (`finish_reason: stop`) e não escreveu nada.

    ⚠️ **Falha real, 02/09/2026, num pânico.** O cliente tocou em «Preciso de
    ajuda!» e o turno morreu: `Resposta vazia do modelo (parada: stop)`. O caso
    foi para a fila humana sem ninguém ter conversado com ele.

    **Parece o `OrcamentoDeTokensEstourado` e não é.** Lá o `finish_reason` é
    `length` e a causa é o teto de tokens; aqui o modelo alega ter concluído.
    A distinção existe porque só a primeira se resolve aumentando orçamento.

    ⭐ **Mas as duas se resolvem tentando de novo com menos raciocínio**, e é
    por isso que esta nasceu: a segunda tentativa existia desde 28/08 e só
    pegava a de cima, então o pânico caía num buraco a dois passos da rede.

    Quem trata são `agent/atendimento_real.py` e `agent/triagem_panico.py`.
    """


class Mensagem(BaseModel):
    papel: Papel
    conteudo: str


class Uso(BaseModel):
    """Consumo de uma chamada. Existe para o custo ser visível durante a POC."""

    tokens_entrada: int = 0
    tokens_saida: int = 0
    tokens_cache_leitura: int = 0
    custo_usd: float | None = Field(
        default=None, description="Quando o provedor informa. `None` quando não."
    )


class RespostaLLM(BaseModel):
    texto: str
    modelo: str = Field(description="O modelo que de fato atendeu — pode diferir do pedido.")
    motivo_parada: str | None = None
    uso: Uso = Field(default_factory=Uso)


class ClienteLLM(Protocol):
    """Contrato único.

    `blocos_sistema` chega como lista, não como texto único, porque a ordem e a
    fronteira entre os blocos é o que define onde o cache é cortado no
    adaptador da Anthropic (persona · guardrails · canal · playbook).
    """

    modelo: str

    async def gerar(
        self,
        *,
        blocos_sistema: list[str],
        mensagens: list[Mensagem],
        max_tokens: int = 1024,
        esforco: Esforco | None = None,
    ) -> RespostaLLM: ...

    async def fechar(self) -> None: ...
