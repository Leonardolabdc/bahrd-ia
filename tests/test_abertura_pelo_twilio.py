"""Abrir a conversa pelo Twilio, que não tem template aprovado.

Este arquivo existe por um defeito encontrado ao ligar o Twilio de verdade, em
15/09/2026: **o canal respondia conversa e nunca conseguia abrir uma**.

`_abrir_com_template` chamava `ClienteMeta` diretamente, sem olhar
`CANAL_WHATSAPP`. Com as credenciais da Meta ausentes — que é o normal quando o
projeto roda em Twilio — ele registrava um aviso e devolvia `False`. Do lado de
fora o sintoma era só "o evento não foi", sem nada apontando para a Meta.

O agravante: os testes do caminho da Meta passavam `object()` como configuração
e nunca declaravam o canal, então exercitavam a Meta **por acidente**, num
projeto cujo padrão é `twilio`. Ninguém estava testando o padrão.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from central_ia.api.rotas import eventos as rota
from central_ia.api.rotas import whatsapp
from central_ia.domain import eventos as catalogo
from central_ia.integrations.mensageria.twilio import MensagemEnviada, TwilioIndisponivel
from central_ia.integrations.rastreamento.bahrd import EventoRastreamento
from central_ia.orchestration.sessao_whatsapp import Sessao, Sessoes

DADOS = {"placa": "ABC1D23", "interlocutor": "Marcos Pereira"}


@pytest.fixture(autouse=True)
def sem_relogio_pendente():
    """Abrir liga o relógio do silêncio; sem isto um teste herda o do anterior."""
    yield
    for ocorrencia in list(whatsapp._ESPERAS):
        whatsapp.cancelar_espera(ocorrencia)


class _so_twilio:
    """Declara o canal que o teste exercita. Ver a docstring do módulo."""

    canal_whatsapp = "twilio"


def _sessao(codigo: str = "REMOCAO_BATERIA") -> Sessao:
    return Sessoes().abrir("+5541999999999", catalogo.por_codigo(codigo), "TEXTO", DADOS)


def _evento(**campos) -> EventoRastreamento:
    base = dict(
        evento_externo_id="x",
        rotulo_link="Remoção de bateria",
        codigo_evento="REMOCAO_BATERIA",
        veiculo="ABC-1234",
        momento=datetime(2026, 8, 24, 12, 0, tzinfo=UTC),
    )
    return EventoRastreamento(**{**base, **campos})


class _TwilioFalso:
    """Guarda o envio. Nada sai para o Twilio — teste não gasta crédito."""

    ultimo: dict = {}

    def __init__(self, cfg) -> None:  # noqa: ARG002
        pass

    async def enviar_texto(self, para: str, corpo: str) -> MensagemEnviada:
        _TwilioFalso.ultimo = {"para": para, "corpo": corpo}
        return MensagemEnviada(sid="SM123", status="queued")

    async def fechar(self) -> None:
        pass


class _TwilioSemCredencial:
    def __init__(self, cfg) -> None:  # noqa: ARG002
        raise TwilioIndisponivel("TWILIO_ACCOUNT_SID ausente.")


class _MetaQueNaoDeveriaSerChamada:
    def __init__(self, cfg) -> None:  # noqa: ARG002
        raise AssertionError(
            "o canal e twilio: a Meta nao pode ser construida aqui. "
            "Foi exatamente este defeito que impedia o Twilio de abrir conversa."
        )


@pytest.mark.asyncio
async def test_com_canal_twilio_a_meta_nao_e_chamada(monkeypatch: pytest.MonkeyPatch) -> None:
    """O teste que representa o defeito. Se a Meta for construída, ele acusa."""
    monkeypatch.setattr(rota, "ClienteTwilio", _TwilioFalso)
    monkeypatch.setattr(rota, "ClienteMeta", _MetaQueNaoDeveriaSerChamada)

    ok = await rota._abrir_com_template(_so_twilio(), _sessao(), _evento())

    assert ok is True


@pytest.mark.asyncio
async def test_o_texto_enviado_e_o_corpo_do_modelo(monkeypatch: pytest.MonkeyPatch) -> None:
    """Não é texto novo: é o mesmo que a Meta entregaria, reconstruído.

    Importa porque o modelo de linguagem lê esse turno como "o que eu já disse".
    Se o texto divergir do que a pessoa recebeu, a IA passa a conversar sobre
    uma mensagem que não existe.
    """
    monkeypatch.setattr(rota, "ClienteTwilio", _TwilioFalso)

    sessao = _sessao()
    await rota._abrir_com_template(_so_twilio(), sessao, _evento())

    corpo = _TwilioFalso.ultimo["corpo"]
    assert corpo, "nada foi enviado"
    assert _TwilioFalso.ultimo["para"] == sessao.telefone

    # O que o painel mostra ao operador precisa estar dentro do que saiu.
    fala_do_template = next((f for f in sessao.falas if f.tipo == "template"), None)
    assert fala_do_template is not None, "o envio nao foi registrado para o operador"
    assert fala_do_template.texto.split("\n")[0] in corpo


@pytest.mark.asyncio
async def test_os_botoes_viram_lista_de_texto(monkeypatch: pytest.MonkeyPatch) -> None:
    """O sandbox não tem botão interativo, e as opções não podem sumir.

    Sem elas, "não respondeu" perde o sentido: a pessoa não sabia que havia
    resposta esperada.
    """
    monkeypatch.setattr(rota, "ClienteTwilio", _TwilioFalso)

    sessao = _sessao()
    await rota._abrir_com_template(_so_twilio(), sessao, _evento())

    corpo = _TwilioFalso.ultimo["corpo"]
    fala = next(f for f in sessao.falas if f.tipo == "template")
    for opcao in fala.botoes:
        assert opcao in corpo, f"a opcao {opcao!r} nao chegou ao cliente"


@pytest.mark.asyncio
async def test_a_coordenada_vira_link_de_mapa(monkeypatch: pytest.MonkeyPatch) -> None:
    """A Meta manda um pino; aqui vai um link. Perder o local é o que não pode."""
    monkeypatch.setattr(rota, "ClienteTwilio", _TwilioFalso)

    await rota._abrir_com_template(
        _so_twilio(), _sessao(), _evento(latitude=-25.4504094, longitude=-49.256198)
    )

    corpo = _TwilioFalso.ultimo["corpo"]
    assert "maps.google.com" in corpo
    assert "-25.4504094" in corpo
    assert "-49.256198" in corpo


@pytest.mark.asyncio
async def test_sem_coordenada_nao_inventa_link(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rota, "ClienteTwilio", _TwilioFalso)

    await rota._abrir_com_template(_so_twilio(), _sessao(), _evento())

    assert "maps.google.com" not in _TwilioFalso.ultimo["corpo"]


@pytest.mark.asyncio
async def test_sem_credencial_devolve_false_sem_levantar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Notificação que não sai é caso a tratar, não exceção a propagar.

    Quem chama esta função está no meio do processamento de um evento. Levantar
    aqui derrubaria a ocorrência inteira por causa do canal.
    """
    monkeypatch.setattr(rota, "ClienteTwilio", _TwilioSemCredencial)

    sessao = _sessao()
    ok = await rota._abrir_com_template(_so_twilio(), sessao, _evento())

    assert ok is False
    assert not any(f.tipo == "template" for f in sessao.falas), (
        "envio que falhou nao pode virar turno: a IA acreditaria ter falado"
    )
