"""Os parâmetros do modelo **de texto** — a reserva, usada sem coordenada.

Escrito em 24/08, quando os templates foram reescritos para ficar iguais à
notificação da Central (doc 12) e a ordem dos parâmetros mudou — antes era
nome e placa. Trocar a ordem sem perceber manda a placa no campo `Local:` e
o endereço no campo `Placa:`, e a mensagem sai errada para o cliente sem
nenhum erro no log.

A escolha entre este modelo e o **com mapa** está em
`test_template_com_mapa.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from central_ia.api.rotas import eventos as rota
from central_ia.api.rotas import whatsapp
from central_ia.domain import eventos as catalogo
from central_ia.integrations.rastreamento.bahrd import EventoRastreamento
from central_ia.orchestration.sessao_whatsapp import Sessoes


@pytest.fixture(autouse=True)
def sem_relogio_pendente():
    """Abrir por template liga o relógio do silêncio nos eventos críticos."""
    yield
    for ocorrencia in list(whatsapp._ESPERAS):
        whatsapp.cancelar_espera(ocorrencia)


#: Um tipo que a POC não trata, para o teste do caminho "fora do catálogo".
#: `TipoEvento` de verdade, não um stub: assim ele tem todos os campos que a
#: rota possa vir a ler, e o teste não quebra no próximo campo novo.
FORA_DO_CATALOGO = catalogo.TipoEvento(
    codigo="EXCESSO_VELOCIDADE",
    rotulo="Evento que a POC não trata",
    criticidade="BAIXA",
    elegivel_ia=False,
)


def _SessaoFalsa(codigo: str):  # noqa: N802 — nome mantido por compatibilidade
    """Uma `Sessao` **de verdade**, não uma imitação.

    Era um dublê com `codigo` e pouco mais. Quebrou três vezes em um dia — a
    cada campo que a rota passou a usar, o dublê estava mentindo sobre a forma
    do objeto real e os testes caíam por motivo alheio ao que eles guardam.
    """
    tipo = catalogo.por_codigo(codigo) or FORA_DO_CATALOGO
    return Sessoes().abrir("+5541999999999", tipo, "TEXTO", {"placa": "ABC-1234"})


class _ClienteFalso:
    """Guarda o que seria enviado. Nada sai para a Meta — teste não gasta."""

    ultimo: dict = {}

    def __init__(self, cfg) -> None:  # noqa: ARG002
        pass

    async def enviar_template(
        self, para, nome, idioma="pt_BR", parametros=None, localizacao=None
    ):
        _ClienteFalso.ultimo = {
            "para": para,
            "nome": nome,
            "parametros": parametros,
            "localizacao": localizacao,
        }
        return {"contacts": [{"wa_id": "5541999999999"}], "messages": [{"id": "wamid.T"}]}

    async def fechar(self) -> None:
        pass


def _evento(**campos) -> EventoRastreamento:
    base = dict(
        evento_externo_id="x",
        rotulo_link="Remoção de bateria",
        codigo_evento="REMOCAO_BATERIA",
        veiculo="ABC-1234",
        momento=datetime(2026, 8, 24, 12, 0, tzinfo=UTC),
    )
    return EventoRastreamento(**{**base, **campos})


class _so_meta:
    """Declara que este teste exercita o caminho da **Meta**.

    Era `object()`. Passava porque `_abrir_com_template` chamava a Meta sem
    olhar `CANAL_WHATSAPP` — e o padrão do projeto é `twilio`. Ou seja: estes
    testes cobriam o canal que não é o padrão, sem dizer isso em lugar nenhum.
    """

    canal_whatsapp = "meta"


@pytest.mark.asyncio
async def test_ordem_e_evento_placa_horario_local(monkeypatch) -> None:
    """Os quatro na ordem certa. A Meta não sabe o que cada um significa.

    Trocar dois de lugar manda o evento no campo da placa e a Meta aceita numa
    boa — a mensagem sai errada para o cliente sem nenhum erro no log.
    """
    monkeypatch.setattr(rota, "ClienteMeta", _ClienteFalso)
    sessao = _SessaoFalsa("REMOCAO_BATERIA")
    evento = _evento(endereco="Rua Comendador Roseira, Curitiba - PR")

    assert await rota._abrir_com_template(_so_meta(), sessao, evento) is True

    assert _ClienteFalso.ultimo["parametros"] == [
        # A abertura entrou como {{1}} em 10/09/2026. Sem `contato_nome` no
        # evento, ela e so a saudacao -- pela hora do EVENTO, nao a de agora.
        "bom dia",
        "Remoção de bateria",
        "ABC-1234",
        "09:00",
        "Rua Comendador Roseira, Curitiba - PR",
    ]


@pytest.mark.asyncio
async def test_horario_sai_no_fuso_de_brasilia(monkeypatch) -> None:
    """⚠️ O guarda que só falha em produção.

    `EventoRastreamento.momento` é UTC, porque o `bahrd_webhook` converte na
    entrada. As 12:00 UTC do evento acima são **09:00** em Brasília, e é isso
    que o motorista precisa ler. Formatar o UTC cru daria 12:00 — três horas
    de erro, invisível na máquina do desenvolvedor, que já está nesse fuso.
    """
    monkeypatch.setattr(rota, "ClienteMeta", _ClienteFalso)

    await rota._abrir_com_template(_so_meta(), _SessaoFalsa("REMOCAO_BATERIA"), _evento())

    # [abertura, evento, placa, horario, local] -- a abertura entrou na frente
    # em 10/09/2026 e empurrou os outros quatro uma casa.
    assert _ClienteFalso.ultimo["parametros"][3] == "09:00"


@pytest.mark.asyncio
async def test_modelo_de_texto_nunca_manda_local_vazio(monkeypatch) -> None:
    """Parâmetro em branco faz a Meta recusar o envio inteiro.

    Evento sem coordenada e sem endereço é o pior caso — e ainda assim o
    `Local:` precisa sair com texto.
    """
    monkeypatch.setattr(rota, "ClienteMeta", _ClienteFalso)

    await rota._abrir_com_template(_so_meta(), _SessaoFalsa("REMOCAO_BATERIA"), _evento())

    parametros = _ClienteFalso.ultimo["parametros"]
    assert parametros[2] == "ABC-1234"
    assert parametros[4] == rota.LOCAL_DESCONHECIDO
    assert all(p.strip() != "" for p in parametros)


@pytest.mark.asyncio
async def test_um_modelo_so_para_bateria_e_movimento(monkeypatch) -> None:
    """O ganho da unificação: o tipo do evento é parâmetro, não modelo.

    Bateria e movimento dividem um modelo, e qualquer outro tipo do catálogo
    caberia ali sem modelo novo — é o que dispensou os quatro modelos que
    existiam antes.

    ⛔ **O pânico é a exceção, e voltou a ser em 10/09/2026.** Ele entrou na
    unificação em 02/09 e saiu de novo: o genérico nomeia o tipo do evento, e o
    rótulo do PANICO no catálogo é "Pânico" — a palavra que o `PB-PANICO`
    proíbe. Unificar aqui custaria a regra que manda em todas as outras.
    """
    monkeypatch.setattr(rota, "ClienteMeta", _ClienteFalso)

    for codigo, esperado in [
        ("REMOCAO_BATERIA", "evento_alerta_pergunta"),
        ("MOVIMENTO_SEM_IGNICAO", "evento_alerta_pergunta"),
        ("PANICO", "evento_panico_saudacao"),
    ]:
        await rota._abrir_com_template(_so_meta(), _SessaoFalsa(codigo), _evento())
        assert _ClienteFalso.ultimo["nome"] == esperado


@pytest.mark.asyncio
async def test_evento_elegivel_sem_permissao_de_notificar_nao_envia(monkeypatch) -> None:
    """A trava que a unificação tornou necessária.

    Antes, quais eventos notificavam era efeito colateral de quais tinham
    modelo. Agora o modelo serve os onze do catálogo — sem
    `EVENTOS_QUE_NOTIFICAM`, a troca de 26/08 faria clientes começarem a
    receber mensagem de velocidade excedida, que eles nunca receberam.

    `VELOCIDADE_EXCEDIDA` é `elegivel_ia`, está no catálogo e mesmo assim não
    fala com o cliente. Só sai dessa lista por decisão de operação.
    """
    monkeypatch.setattr(rota, "ClienteMeta", _ClienteFalso)
    _ClienteFalso.ultimo = {}

    assert "VELOCIDADE_EXCEDIDA" not in rota.EVENTOS_QUE_NOTIFICAM
    ok = await rota._abrir_com_template(_so_meta(), _SessaoFalsa("VELOCIDADE_EXCEDIDA"), _evento())

    assert ok is False
    assert _ClienteFalso.ultimo == {}


@pytest.mark.asyncio
async def test_evento_sem_template_nao_envia(monkeypatch) -> None:
    """Fora do catálogo não abre conversa — e não gasta os R$ 0,034."""
    monkeypatch.setattr(rota, "ClienteMeta", _ClienteFalso)
    _ClienteFalso.ultimo = {}

    ok = await rota._abrir_com_template(_so_meta(), _SessaoFalsa("EXCESSO_VELOCIDADE"), _evento())

    assert ok is False
    assert _ClienteFalso.ultimo == {}
