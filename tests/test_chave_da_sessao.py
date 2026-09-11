"""A chave que liga a resposta do motorista à conversa que a IA abriu.

**Bug real, 24/08/2026.** O primeiro evento disparado pelo Postman abriu a
ocorrência com `+5541999999999` (do payload da Bahrd). O motorista respondeu, a
Meta reportou `554199999999` — sem o nono dígito —, a sessão não foi
encontrada, e ele recebeu **o menu de ajuda no meio do atendimento**.

O sintoma engana porque nada falha: o sistema trata como conversa nova e segue
normalmente. Sem estes testes, volta na primeira refatoração.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from central_ia.domain import eventos
from central_ia.orchestration.sessao_whatsapp import SESSOES, _chave

TIPO = eventos.por_codigo("MOVIMENTO_SEM_IGNICAO")


@pytest.fixture(autouse=True)
def limpar():
    SESSOES.limpar()
    yield
    SESSOES.limpar()


# ─────────────────────────── a canonização ───────────────────────────


@pytest.mark.parametrize(
    "escrito",
    [
        "+5541999999999",          # payload da Bahrd, com o nono dígito
        "554199999999",            # Meta no webhook, sem o nono
        "5541999999999",           # sem o '+'
        "whatsapp:+5541999999999",  # Twilio
        "+55 (41) 99999-9999",     # com máscara
    ],
)
def test_todas_as_grafias_dao_a_mesma_chave(escrito: str) -> None:
    assert _chave(escrito) == "554199999999"


def test_numeros_diferentes_nao_colidem() -> None:
    assert _chave("+5541999999999") != _chave("+5541988888888")


def test_fixo_nao_e_transformado() -> None:
    """Só celular brasileiro tem nono dígito. Fixo passa direto."""
    assert _chave("+554133334444") == "554133334444"


def test_numero_estrangeiro_passa_direto() -> None:
    assert _chave("+15556727656") == "15556727656"


# ─────────────────── o comportamento que o bug quebrou ───────────────────


def test_resposta_sem_o_nono_digito_encontra_a_sessao() -> None:
    """O caso exato de 24/08: abre com 13 dígitos, responde com 12."""
    SESSOES.abrir("+5541999999999", TIPO, "TEXTO", {})

    assert SESSOES.ativa("554199999999") is not None


def test_resposta_com_o_nono_digito_encontra_a_sessao() -> None:
    """E o inverso — a Bahrd pode passar a mandar sem o 9."""
    SESSOES.abrir("554199999999", TIPO, "TEXTO", {})

    assert SESSOES.ativa("+5541999999999") is not None


def test_formato_do_twilio_encontra_a_sessao_aberta_pela_meta() -> None:
    """Os dois canais convivem — a sessão não pode depender de qual abriu."""
    SESSOES.abrir("554199999999", TIPO, "TEXTO", {})

    assert SESSOES.ativa("whatsapp:+5541999999999") is not None


def test_outro_numero_nao_entra_na_conversa_alheia() -> None:
    """A canonização não pode aproximar demais: seria a IA falando com a pessoa
    errada, que é pior que não achar a sessão."""
    SESSOES.abrir("+5541999999999", TIPO, "TEXTO", {})

    assert SESSOES.ativa("+5541988888888") is None


# ─────────────── resposta depois que o atendimento fechou ───────────────


def test_encontra_a_conversa_que_fechou_ha_pouco() -> None:
    """Bug real, 24/08/2026: a pessoa respondeu depois do encerramento e
    recebeu o menu de teste da POC — *"mande bateria, ignicao ou panico"* — no
    meio de um atendimento que acabara de ser fechado."""
    sessao = SESSOES.abrir("+5541999999999", TIPO, "TEXTO", {})
    sessao.encerrar("escalado_pela_ia")

    achada = SESSOES.encerrada_ha_pouco("554199999999", timedelta(minutes=20))

    assert achada is not None
    assert achada.ocorrencia_id == sessao.ocorrencia_id


def test_conversa_antiga_nao_conta() -> None:
    """Passada a janela, a mensagem é assunto novo — aí o menu faz sentido."""
    sessao = SESSOES.abrir("+5541999999999", TIPO, "TEXTO", {})
    sessao.encerrar("encerrado")
    sessao.ultima_em = datetime.now(UTC) - timedelta(hours=3)

    assert SESSOES.encerrada_ha_pouco("554199999999", timedelta(minutes=20)) is None


def test_numero_sem_historico_nao_encontra_nada() -> None:
    assert SESSOES.encerrada_ha_pouco("5511999999999", timedelta(minutes=20)) is None


def test_guarda_o_canal_para_responder_no_mesmo_meio() -> None:
    """Quem falou por áudio recebe áudio também no aviso de encerramento."""
    sessao = SESSOES.abrir("+5541999999999", TIPO, "AUDIO", {})
    sessao.encerrar("encerrado")

    achada = SESSOES.encerrada_ha_pouco("554199999999", timedelta(minutes=20))

    assert achada.canal == "AUDIO"
