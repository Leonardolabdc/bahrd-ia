"""O mesmo evento, entregue duas vezes, vira uma ocorrência só.

**Defeito real, 01/09/2026, achado num teste de frota.** O `_derivar_id` já
existia e o docstring dele já se chamava "chave de idempotência"; o `main.py`
já dizia que a API "deduplica". Mas ninguém conferia: a chave era calculada,
escrita no log e jogada fora.

O que apareceu no teste, nos logs de 18:25 a 18:26:

    evento 580b1f37…  placa AJL2532  →  OC-2026-09-01-A819-WA
    evento 580b1f37…  placa AJL2532  →  OC-2026-09-01-5653-WA   ← 42 s depois

Duas ocorrências, mesma placa, mesmo evento. No painel viraram dois
atendimentos idênticos; no celular, duas notificações iguais.

Em produção não depende de alguém repetir o teste: webhook é entrega **pelo
menos uma vez**, e a Bahrd reentrega sempre que a primeira resposta demorar.
Cada reentrega abriria mais uma ocorrência e mandaria mais um template, que é
cobrado.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from central_ia.api.rotas import eventos as rota
from central_ia.integrations.rastreamento.bahrd_webhook import _derivar_id


@pytest.fixture(autouse=True)
def limpar():
    rota.esquecer_eventos()
    yield
    rota.esquecer_eventos()


# ─────────────────────── a chave, que já existia ───────────────────────


def test_o_mesmo_payload_da_a_mesma_chave() -> None:
    """É o que torna a deduplicação possível sem `id` da Bahrd."""
    momento = datetime(2026, 9, 1, 18, 25, 50, tzinfo=UTC)
    primeira = _derivar_id("AJL2532", "Remoção de bateria", momento)
    segunda = _derivar_id("AJL2532", "Remoção de bateria", momento)

    assert primeira == segunda


def test_alarmes_de_verdade_do_mesmo_veiculo_dao_chaves_diferentes() -> None:
    """⚠️ A trava não pode calar o segundo alarme real do mesmo caminhão.

    O momento entra na semente justamente para isso: o que a memória barra é a
    **repetição do mesmo evento**, nunca a repetição do mesmo veículo.
    """
    manha = datetime(2026, 9, 1, 8, 0, 0, tzinfo=UTC)
    tarde = datetime(2026, 9, 1, 15, 30, 0, tzinfo=UTC)

    assert _derivar_id("AJL2532", "Remoção de bateria", manha) != _derivar_id(
        "AJL2532", "Remoção de bateria", tarde
    )


def test_veiculos_diferentes_nao_colidem() -> None:
    momento = datetime(2026, 9, 1, 18, 25, 50, tzinfo=UTC)

    assert _derivar_id("AJL2532", "Remoção de bateria", momento) != _derivar_id(
        "AKK9832", "Remoção de bateria", momento
    )


# ─────────────────────── a memória, que faltava ───────────────────────


def test_evento_atendido_e_reconhecido_na_segunda_vez() -> None:
    """O caso do log: mesmo evento, 42 s depois."""
    assert rota._ja_atendido("580b1f37") is False

    rota._registrar_atendido("580b1f37")

    assert rota._ja_atendido("580b1f37") is True


def test_evento_que_nao_foi_atendido_nao_e_barrado() -> None:
    """⭐ A ordem que importa: registra só o que deu certo.

    Se a primeira tentativa falhou — Meta fora do ar, template recusado — a
    reentrega da Bahrd **tem** de passar. Marcar antes de atender transformaria
    uma falha nossa em evento perdido para sempre.
    """
    assert rota._ja_atendido("nunca-atendido") is False
    assert rota._ja_atendido("nunca-atendido") is False


def test_a_memoria_expira() -> None:
    """Seis horas depois, o mesmo evento volta a ser novidade.

    Não é um detalhe: memória que não expira é vazamento, e a chave inclui o
    momento, então um evento velho não tem por que continuar reservado.
    """
    rota._registrar_atendido("580b1f37")
    assert rota._ja_atendido("580b1f37") is True

    rota._ATENDIDOS["580b1f37"] = datetime.now(UTC) - rota.MEMORIA_DE_EVENTOS - timedelta(minutes=1)

    assert rota._ja_atendido("580b1f37") is False


def test_a_poda_nao_derruba_os_vizinhos() -> None:
    """Expirar um não pode limpar a memória inteira."""
    rota._registrar_atendido("velho")
    rota._registrar_atendido("novo")
    rota._ATENDIDOS["velho"] = datetime.now(UTC) - rota.MEMORIA_DE_EVENTOS - timedelta(minutes=1)

    assert rota._ja_atendido("velho") is False
    assert rota._ja_atendido("novo") is True


def test_eventos_diferentes_nao_se_barram() -> None:
    """As duas placas do teste real: uma atendida não pode calar a outra."""
    rota._registrar_atendido("580b1f37")  # AJL2532

    assert rota._ja_atendido("acd329ae") is False  # AKK9832
