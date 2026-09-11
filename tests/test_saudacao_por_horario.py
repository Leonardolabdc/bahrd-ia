"""A saudação vem do relógio de Brasília, não do modelo.

O modelo não sabe que horas são. Sem receber isso no contexto, ele chuta — e
"bom dia" às 22h denuncia a máquina antes da primeira pergunta.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from central_ia.agent.atendimento_real import (
    FUSO_OPERACAO,
    nota_do_horario,
    saudacao_do_momento,
)

UTC = ZoneInfo("UTC")


def _em_brasilia(hora: int) -> datetime:
    return datetime(2026, 8, 24, hora, 30, tzinfo=FUSO_OPERACAO)


@pytest.mark.parametrize(
    ("hora", "esperado"),
    [
        (5, "Bom dia"), (8, "Bom dia"), (11, "Bom dia"),
        (12, "Boa tarde"), (15, "Boa tarde"), (17, "Boa tarde"),
        (18, "Boa noite"), (22, "Boa noite"), (23, "Boa noite"),
        (0, "Boa noite"), (3, "Boa noite"),
    ],
)
def test_saudacao_por_periodo(hora: int, esperado: str) -> None:
    assert saudacao_do_momento(_em_brasilia(hora)) == esperado


def test_usa_brasilia_e_nao_o_relogio_do_servidor() -> None:
    """O contêiner roda em UTC. 23h em Brasília é 2h do dia seguinte em UTC —
    saudar pelo relógio do servidor daria a saudação errada por três horas."""
    vinte_e_tres_em_brasilia = datetime(2026, 8, 25, 2, 0, tzinfo=UTC)

    assert saudacao_do_momento(vinte_e_tres_em_brasilia) == "Boa noite"


# ─────────────────────────── a nota da madrugada ───────────────────────────


@pytest.mark.parametrize("hora", [0, 2, 5])
def test_madrugada_pede_para_reconhecer_o_horario(hora: int) -> None:
    """Operador de verdade que fala às 3h reconhece a hora. É o que separa
    atendimento de robô."""
    assert nota_do_horario(_em_brasilia(hora)) != ""


@pytest.mark.parametrize("hora", [6, 10, 14, 19, 22])
def test_horario_normal_nao_gera_nota(hora: int) -> None:
    """Pedir desculpa às 14h chamaria atenção para nada — e IA que se explica
    demais soa insegura."""
    assert nota_do_horario(_em_brasilia(hora)) == ""


def test_a_saudacao_entra_no_contexto_da_ocorrencia() -> None:
    """Guarda o elo: sem isso no contexto, o modelo volta a chutar a hora."""
    from central_ia.agent.atendimento_real import contexto_inicial
    from central_ia.domain import eventos

    texto = contexto_inicial(eventos.por_codigo("REMOCAO_BATERIA"), {}, com_operador=False)

    assert "saudação correta para a hora de agora" in texto
    assert saudacao_do_momento() in texto
