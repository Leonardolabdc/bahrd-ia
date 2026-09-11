"""Geração de um atendimento completo, com o playbook real.

A IA conduz; um segundo modelo faz o papel do interlocutor. É o *simulador de
cliente* previsto no doc 03 §7 — o que permite exercitar playbook, tom e
escalonamento sem incomodar um motorista de verdade.

Duas escolhas de desenho que valem registro:

* **O contexto da ocorrência entra em `messages`, nunca em `system`.** Colocá-lo
  no bloco de sistema quebraria o cache de prompt a cada atendimento — é a
  regra de ouro do doc 02 §6.1.
* **O simulador de cliente não vê os guardrails nem o playbook.** Ele recebe só
  a situação e um temperamento. Se visse o procedimento, cooperaria com ele e o
  teste provaria nada.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from central_ia.agent import prompts
from central_ia.agent.esforco import esforco_do_canal
from central_ia.domain.eventos import TipoEvento
from central_ia.ports.llm import ClienteLLM, Mensagem

Temperamento = Literal["cooperativo", "evasivo", "nega_tudo"]

#: Turnos da IA. Os playbooks miram 3 a 5; acima disso já é sinal de que a
#: conversa devia ter sido escalada.
MAX_TURNOS = 4

TEMPERAMENTOS: dict[Temperamento, str] = {
    "cooperativo": (
        "Você responde de boa vontade, com frases curtas de quem está na estrada. "
        "A causa do alerta é normal e você a explica quando perguntado."
    ),
    "evasivo": (
        "Você responde de forma vaga, sem confirmar nem negar. Está com pressa "
        "e não entra em detalhe."
    ),
    "nega_tudo": (
        "Você nega o que a central sugere e diz que não está perto do veículo. "
        "Não é hostil, apenas não confirma nada."
    ),
}


@dataclass
class Turno:
    quem: Literal["ia", "cliente"]
    fala: str


@dataclass
class Atendimento:
    turnos: list[Turno]
    custo_usd: float
    tokens_entrada: int
    tokens_saida: int


def _contexto_da_ocorrencia(tipo: TipoEvento, dados: dict[str, str]) -> str:
    linhas = "\n".join(f"- {chave}: {valor}" for chave, valor in dados.items())
    return (
        f"Contexto da ocorrência em atendimento:\n"
        f"- tipo de evento: {tipo.rotulo}\n"
        f"- criticidade: {tipo.criticidade}\n"
        f"- janela para escalonamento: {tipo.janela_s} segundos\n"
        f"{linhas}\n\n"
        "Conduza o atendimento conforme o playbook. Fale apenas a sua próxima "
        "mensagem, sem narrar o que está fazendo."
    )


def _prompt_do_cliente(tipo: TipoEvento, dados: dict[str, str], temperamento: Temperamento) -> str:
    return (
        f"Você é {dados.get('interlocutor', 'o motorista')}, de um caminhão de carga no Brasil. "
        f"A central de monitoramento entrou em contato por causa de um alerta de "
        f"'{tipo.rotulo}' no veículo {dados.get('placa', '')}.\n\n"
        f"{TEMPERAMENTOS[temperamento]}\n\n"
        "Responda como a pessoa responderia: uma ou duas frases, linguagem falada, "
        "sem formalidade. Fale só a sua resposta, nada mais."
    )


async def gerar(
    cliente: ClienteLLM,
    tipo: TipoEvento,
    canal: str,
    dados: dict[str, str],
    temperamento: Temperamento = "cooperativo",
) -> Atendimento:
    blocos = prompts.blocos_de_sistema(tipo, canal)

    historico: list[Mensagem] = [
        Mensagem(papel="user", conteudo=_contexto_da_ocorrencia(tipo, dados))
    ]
    turnos: list[Turno] = []
    custo = 0.0
    entrada = saida = 0

    for indice in range(MAX_TURNOS):
        # `effort` baixo na voz é o que o plano prevê: turnos curtos por design.
        resposta_ia = await cliente.gerar(
            blocos_sistema=blocos,
            mensagens=historico,
            max_tokens=300,
            esforco=esforco_do_canal(canal),
        )
        fala_ia = " ".join(resposta_ia.texto.split())
        if not fala_ia:
            break

        turnos.append(Turno("ia", fala_ia))
        historico.append(Mensagem(papel="assistant", conteudo=fala_ia))
        custo += resposta_ia.uso.custo_usd or 0.0
        entrada += resposta_ia.uso.tokens_entrada
        saida += resposta_ia.uso.tokens_saida

        if indice == MAX_TURNOS - 1:
            break

        # O simulador recebe só a conversa e um temperamento — nunca o playbook.
        resposta_cliente = await cliente.gerar(
            blocos_sistema=[_prompt_do_cliente(tipo, dados, temperamento)],
            mensagens=[
                Mensagem(
                    papel="user",
                    conteudo="Conversa até agora:\n"
                    + "\n".join(f"{t.quem}: {t.fala}" for t in turnos)
                    + "\n\nSua resposta:",
                )
            ],
            max_tokens=160,
        )
        fala_cliente = " ".join(resposta_cliente.texto.split())
        if not fala_cliente:
            break

        turnos.append(Turno("cliente", fala_cliente))
        historico.append(Mensagem(papel="user", conteudo=fala_cliente))
        custo += resposta_cliente.uso.custo_usd or 0.0
        entrada += resposta_cliente.uso.tokens_entrada
        saida += resposta_cliente.uso.tokens_saida

    return Atendimento(turnos, custo, entrada, saida)
