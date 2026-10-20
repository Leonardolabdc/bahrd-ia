"""«Contenção ao longo do dia», de volta à Visão geral com dado de verdade.

⭐ A Visão geral ganhou o desenho em quadros do painel de referência, e o
gráfico de linha voltou junto — desta vez com `_contencao_por_hora` calculando
de verdade, em vez do array fixo de 20 números que `amostra.metricas()` usa
como moldura. A regra que importa: hora sem caso é vazia, nunca "0%".

⭐ 20/10/2026, pedido do Leonardo: sem nenhum caso real hoje, a tela volta a
mostrar a curva de amostra (o mesmo array fixo de `amostra.metricas()`) em vez
da moldura vazia — mesmo padrão já usado pelo vital «Encerradas»: dado real
sobrescreve quando existe, amostra continua de pé quando não há nada ainda.
`_contencao_por_hora` sozinha continua honesta (devolve `[]` sem caso real);
é só `obter_metricas()`, a rota, que decide manter a amostra nesse caso.
"""

from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from central_ia.api import amostra
from central_ia.api.rotas.painel import (
    FUSO_PAINEL,
    _contencao_por_hora,
    obter_encerrados,
    obter_metricas,
)
from central_ia.domain import eventos
from central_ia.orchestration.sessao_whatsapp import SESSOES


@pytest.fixture(autouse=True)
def _limpar():
    SESSOES.limpar()
    yield
    SESSOES.limpar()


def _serie() -> list[int | None]:
    return asyncio.run(obter_metricas()).contencao_por_hora


def _abrir(telefone: str, placa: str):  # noqa: ANN202
    return SESSOES.abrir(telefone, eventos.REMOCAO_BATERIA, "TEXTO", {"placa": placa})


def test_a_funcao_pura_sem_nenhum_caso_devolve_vazio() -> None:
    """`_contencao_por_hora` por si só continua honesta: sem caso, é `[]`."""
    fechadas = asyncio.run(obter_encerrados())
    assert _contencao_por_hora(fechadas) == []


def test_sem_nenhum_caso_real_a_rota_mantem_a_amostra() -> None:
    """A rota inteira, sem caso real hoje, não mostra moldura vazia — mantém
    a curva de amostra que já vem de `amostra.metricas()`."""
    assert _serie() == amostra.metricas().contencao_por_hora


def test_a_hora_mostra_quanto_a_ia_fechou_sozinha() -> None:
    _abrir("+5541999990001", "AAA1A11").encerrar(
        "encerrada_pela_ia", desfecho="veiculo_em_manutencao"
    )
    _abrir("+5541999990002", "AAA1A12").escalada = True

    serie = _serie()
    agora = datetime.now(FUSO_PAINEL).hour
    assert len(serie) == agora + 1, "de 00h até a hora atual"
    assert serie[agora] == 50, "1 fechado pela IA de 2 atendidos nesta hora"
    assert all(v is None for v in serie[:agora]), "hora sem caso é vazia, não 0%"
