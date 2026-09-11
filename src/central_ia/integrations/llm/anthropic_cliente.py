"""Adaptador da Anthropic — o destino.

Aqui existe o que o OpenRouter não tem, e que o projeto foi desenhado em cima:

* **Cache de prompt.** O `cache_control` vai no **último** bloco de sistema,
  fechando o prefixo estável (persona · guardrails · canal · playbook) com TTL
  de 1 hora. A partir do segundo turno esse trecho é relido a 10% do preço — é
  o que sustenta o orçamento de latência de voz (doc 02 §6.1).
* **Thinking adaptativo e `effort`.** `low` na voz, `high` na triagem.

Regra de ouro do cache: nada de data, UUID ou nome de cliente nos blocos de
sistema. Contexto da ocorrência entra em `messages`, nunca em `system`.
"""

from __future__ import annotations

import anthropic

from central_ia.config import Settings
from central_ia.ports.llm import (
    Esforco,
    Mensagem,
    OrcamentoDeTokensEstourado,
    RespostaLLM,
    Uso,
)


class ClienteAnthropic:
    def __init__(self, cfg: Settings, modelo: str | None = None) -> None:
        if cfg.anthropic_api_key is None:
            raise RuntimeError("ANTHROPIC_API_KEY ausente. Preencha o .env e salve o arquivo.")

        self.modelo = modelo or cfg.anthropic_modelo_principal
        self._cliente = anthropic.AsyncAnthropic(
            api_key=cfg.anthropic_api_key.get_secret_value()
        )

    def _system(self, blocos: list[str]) -> list[dict]:
        """Monta os blocos com o breakpoint de cache no fim do último."""
        uteis = [b for b in blocos if b]
        blocos_api: list[dict] = [{"type": "text", "text": b} for b in uteis]
        if blocos_api:
            blocos_api[-1]["cache_control"] = {"type": "ephemeral", "ttl": "1h"}
        return blocos_api

    async def gerar(
        self,
        *,
        blocos_sistema: list[str],
        mensagens: list[Mensagem],
        max_tokens: int = 1024,
        esforco: Esforco | None = None,
    ) -> RespostaLLM:
        parametros: dict = {
            "model": self.modelo,
            "max_tokens": max_tokens,
            "system": self._system(blocos_sistema),
            "messages": [{"role": m.papel, "content": m.conteudo} for m in mensagens],
            "thinking": {"type": "adaptive"},
        }
        if esforco:
            parametros["output_config"] = {"effort": esforco}

        resposta = await self._cliente.messages.create(**parametros)

        # Recusa é tratada ANTES de ler o conteúdo: falha vira humano, nunca
        # fechamento automático (princípio 2).
        if resposta.stop_reason == "refusal":
            raise RuntimeError("O modelo recusou a solicitação — escalar para humano.")

        texto = "".join(b.text for b in resposta.content if b.type == "text")

        # Mesmo estouro que derrubou um atendimento no OpenRouter em 28/08. Aqui
        # o raciocínio sai de um orçamento à parte, então é menos provável, mas
        # "menos provável" não é "impossível" e o sintoma seria idêntico: a IA
        # entrega uma mensagem vazia a quem está esperando resposta.
        if not texto.strip() and resposta.stop_reason == "max_tokens":
            raise OrcamentoDeTokensEstourado(
                f"O modelo consumiu os {max_tokens} tokens sem produzir conteúdo "
                f"(esforço={esforco}). Aumente max_tokens ou reduza o esforço."
            )

        return RespostaLLM(
            texto=texto,
            modelo=resposta.model,
            motivo_parada=resposta.stop_reason,
            uso=Uso(
                tokens_entrada=resposta.usage.input_tokens,
                tokens_saida=resposta.usage.output_tokens,
                tokens_cache_leitura=getattr(resposta.usage, "cache_read_input_tokens", 0) or 0,
            ),
        )

    async def fechar(self) -> None:
        await self._cliente.close()
