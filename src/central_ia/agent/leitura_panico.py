"""Leitura de contexto para eventos que a IA nunca conduz.

Pânico, roubo ativo e afins vão direto para o operador humano. A IA não fala
com ninguém — ela apenas lê telemetria e histórico e devolve **uma leitura de
uma linha** para a tela, para o operador decidir mais rápido.

Duas travas, e as duas importam:

1. **O prompt não pede recomendação.** Ele pede descrição. A diferença entre
   "veículo em rota a 82 km/h, sem outros eventos" e "provável acionamento
   acidental" é a diferença entre informar e induzir — e induzir num evento de
   pânico pode matar alguém.
2. **A saída é truncada e verificada.** Se o modelo escorregar para conselho, o
   texto é descartado e o operador recebe só os fatos da telemetria. Falha aqui
   nunca vira silêncio: vira menos informação, nunca informação errada.
"""

from __future__ import annotations

import re

from central_ia.domain.eventos import TipoEvento
from central_ia.ports.llm import ClienteLLM, Mensagem

#: Cobre raciocínio e resposta juntos — ver a nota no adaptador do OpenRouter.
MAX_TOKENS = 600

INSTRUCAO = """\
Você apoia um operador humano de uma central de monitoramento de frotas.

O evento abaixo é crítico e está sendo atendido por uma pessoa. Você NÃO fala
com ninguém e NÃO conduz o atendimento.

Sua única tarefa é ler os dados e escrever uma leitura de contexto de duas ou
três frases, para a tela do operador, com o que ajuda a decidir mais rápido.

Escreva apenas fatos observáveis: posição, velocidade, rota, eventos anteriores
do mesmo equipamento. Português do Brasil, direto, sem saudação.

Não recomende nada. Não diga o que provavelmente aconteceu, não classifique o
risco, não sugira ação nem desfecho. O operador decide; você informa.\
"""

# Um verbo destes indica que o modelo passou de descrever para aconselhar.
SINAIS_DE_RECOMENDACAO = re.compile(
    r"\b(recomend|sugir|sugest|deve[- ]se|é prudente|aconselh|provavelmente|"
    r"possivelmente|indica que|trata-se de|parece ser|priorize|acione)",
    re.IGNORECASE,
)


def _fatos(contexto: dict[str, str]) -> str:
    return "\n".join(f"{chave}: {valor}" for chave, valor in contexto.items())


async def gerar(
    cliente: ClienteLLM, tipo: TipoEvento, contexto: dict[str, str]
) -> tuple[str, bool, float]:
    """Devolve `(leitura, foi_gerada_pela_ia, custo_usd)`.

    Quando a saída é descartada por conter recomendação, volta a leitura
    factual montada em código — informação a menos, nunca informação errada.
    """
    resposta = await cliente.gerar(
        blocos_sistema=[INSTRUCAO],
        mensagens=[
            Mensagem(
                papel="user",
                conteudo=(
                    f"Evento: {tipo.rotulo} (criticidade {tipo.criticidade})\n\n"
                    f"{_fatos(contexto)}"
                ),
            )
        ],
        max_tokens=MAX_TOKENS,
    )

    texto = " ".join(resposta.texto.split())
    custo = resposta.uso.custo_usd or 0.0

    if not texto or SINAIS_DE_RECOMENDACAO.search(texto):
        return _leitura_de_reserva(contexto), False, custo

    return texto, True, custo


def _leitura_de_reserva(contexto: dict[str, str]) -> str:
    """Só os fatos, sem modelo nenhum no caminho."""
    partes = [f"{chave.lower()} {valor}" for chave, valor in contexto.items()]
    return "Leitura automática indisponível. Telemetria: " + "; ".join(partes) + "."
