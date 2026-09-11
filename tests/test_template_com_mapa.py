"""A escolha entre o modelo com mapa e o de texto, e por que ela existe.

Modelo com cabeçalho `LOCATION` **exige** o bloco de localização preenchido —
é campo obrigatório, como qualquer `{{1}}`. Mandar sem ele faz a Meta recusar,
e aí o motorista não recebe o mapa *nem o aviso do alarme*.

Por isso os dois conjuntos existem, e por isso estes testes.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from central_ia.api.rotas import eventos as rota
from central_ia.api.rotas import whatsapp
from central_ia.domain import eventos as catalogo
from central_ia.integrations.mensageria.meta import MetaIndisponivel
from central_ia.integrations.rastreamento.bahrd import EventoRastreamento
from central_ia.orchestration.sessao_whatsapp import Sessao, Sessoes

DADOS = {"placa": "ABC-1234", "interlocutor": "Antônio da Silva"}


@pytest.fixture(autouse=True)
def sem_relogio_pendente():
    """Abrir por template liga o relógio do silêncio nos eventos críticos.

    Sem esta limpeza, cada teste deixa uma tarefa `asyncio` viva e o próximo
    herda o relógio do anterior.
    """
    yield
    for ocorrencia in list(whatsapp._ESPERAS):
        whatsapp.cancelar_espera(ocorrencia)


def _SessaoFalsa(codigo: str) -> Sessao:  # noqa: N802 — nome mantido por compatibilidade
    """Uma `Sessao` **de verdade**, não uma imitação.

    Era um dublê com `codigo` e pouco mais. Quebrou três vezes em um dia — a
    cada campo ou método que a rota passou a usar, o dublê estava mentindo
    sobre a forma do objeto real e os testes caíam por motivo que não tinha
    nada a ver com o que eles guardam. Com a `Sessao` real isso acaba: o que
    passa aqui passa em produção.
    """
    return Sessoes().abrir("+5541999999999", catalogo.por_codigo(codigo), "TEXTO", DADOS)


class _ClienteFalso:
    """Guarda o envio. Nada sai para a Meta — teste não gasta."""

    ultimo: dict = {}

    def __init__(self, cfg) -> None:  # noqa: ARG002
        pass

    async def enviar_template(self, para, nome, idioma="pt_BR", parametros=None, localizacao=None):
        _ClienteFalso.ultimo = {
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


# ─────────────────────────── o bloco de mapa ───────────────────────────


def test_coordenada_vira_bloco_de_mapa() -> None:
    mapa = rota.localizacao_do_evento(_evento(latitude=-25.4504094, longitude=-49.256198))

    assert mapa == {
        "latitude": "-25.4504094",
        "longitude": "-49.256198",
        "name": "ABC-1234",
        "address": "-25.45041, -49.25620",
    }


def test_o_bloco_de_mapa_sempre_tem_endereco() -> None:
    """⚠️ `address` é obrigatório, e descobrir isso custou o mapa em produção.

    Em 27/08/2026, no primeiro disparo real, a Meta devolveu «Parameter
    'address' is mandatory for component parameter type 'location'». Mandá-lo
    só quando havia endereço era o pior caso possível: **a Bahrd não manda
    `endereco`**, então o modelo com mapa falhava sempre e a notificação saía
    sempre pela reserva de texto. O mapa nunca teria funcionado, e o único
    sintoma era um `template_falhou` no log — a mensagem chegava bonitinha.
    """
    for evento in [
        _evento(latitude=-25.45, longitude=-49.25),
        _evento(latitude=-25.45, longitude=-49.25, objeto_geografico="Pátio da Matriz"),
        _evento(latitude=-25.45, longitude=-49.25, endereco="Rua Comendador Roseira"),
        _evento(latitude=0.0, longitude=0.0),
    ]:
        mapa = rota.localizacao_do_evento(evento)
        assert mapa is not None
        assert mapa.get("address"), "bloco de mapa sem address — a Meta recusa"


def test_endereco_entra_no_mapa_quando_existe() -> None:
    mapa = rota.localizacao_do_evento(
        _evento(latitude=-25.45, longitude=-49.25, endereco="Rua Comendador Roseira")
    )

    assert mapa["address"] == "Rua Comendador Roseira"


def test_sem_coordenada_nao_ha_mapa() -> None:
    assert rota.localizacao_do_evento(_evento()) is None


def test_meia_coordenada_nao_ha_mapa() -> None:
    """Latitude sem longitude não localiza nada — e mandaria o envio ao chão."""
    assert rota.localizacao_do_evento(_evento(latitude=-25.45)) is None
    assert rota.localizacao_do_evento(_evento(longitude=-49.25)) is None


def test_coordenada_zero_ainda_e_coordenada() -> None:
    """`0.0` é falsy em Python — o teste que impede um `if not lat` distraído."""
    mapa = rota.localizacao_do_evento(_evento(latitude=0.0, longitude=0.0))

    assert mapa is not None
    assert mapa["latitude"] == "0.0"


# ─────────────────────────── a escolha do modelo ───────────────────────────


@pytest.mark.asyncio
async def test_com_coordenada_usa_o_modelo_com_mapa(monkeypatch) -> None:
    monkeypatch.setattr(rota, "ClienteMeta", _ClienteFalso)

    await rota._abrir_com_template(
        object(), _SessaoFalsa("REMOCAO_BATERIA"), _evento(latitude=-25.45, longitude=-49.25)
    )

    assert _ClienteFalso.ultimo["nome"] == "evento_alerta_pergunta_mapa"
    assert _ClienteFalso.ultimo["localizacao"] is not None
    # ⛔ Sem endereço, o `Local:` mostra a coordenada -- a MESMA que o cartão
    # mostra. Antes mandava "veja o mapa acima" enquanto o cartão exibia os
    # números, e os dois falavam do mesmo ponto com textos diferentes.
    assert _ClienteFalso.ultimo["parametros"] == [
        # A abertura entrou como {{1}} em 10/09/2026. Sem `contato_nome` no
        # evento, ela e so a saudacao -- pela hora do EVENTO, nao a de agora.
        "bom dia",
        "Remoção de bateria",
        "ABC-1234",
        "09:00",
        "-25.45000, -49.25000",
    ]
    assert (
        _ClienteFalso.ultimo["localizacao"]["address"]
        == _ClienteFalso.ultimo["parametros"][4]
    ), "cartão e corpo dizem o mesmo endereço"


@pytest.mark.asyncio
async def test_sem_coordenada_cai_no_modelo_de_texto(monkeypatch) -> None:
    """A reserva. É ela que garante que a notificação sai de qualquer forma."""
    monkeypatch.setattr(rota, "ClienteMeta", _ClienteFalso)

    ok = await rota._abrir_com_template(object(), _SessaoFalsa("REMOCAO_BATERIA"), _evento())

    assert ok is True
    assert _ClienteFalso.ultimo["nome"] == "evento_alerta_pergunta"
    assert _ClienteFalso.ultimo["localizacao"] is None
    assert _ClienteFalso.ultimo["parametros"] == [
        # A abertura entrou como {{1}} em 10/09/2026. Sem `contato_nome` no
        # evento, ela e so a saudacao -- pela hora do EVENTO, nao a de agora.
        "bom dia",
        "Remoção de bateria",
        "ABC-1234",
        "09:00",
        rota.LOCAL_DESCONHECIDO,
    ]


@pytest.mark.asyncio
async def test_nunca_manda_modelo_com_mapa_sem_o_bloco(monkeypatch) -> None:
    """O erro que este desenho inteiro existe para impedir."""
    monkeypatch.setattr(rota, "ClienteMeta", _ClienteFalso)

    for evento in [_evento(), _evento(latitude=-25.45), _evento(longitude=-49.25)]:
        await rota._abrir_com_template(object(), _SessaoFalsa("REMOCAO_BATERIA"), evento)
        enviado = _ClienteFalso.ultimo
        if enviado["nome"].endswith("_mapa"):
            assert enviado["localizacao"] is not None, "modelo com mapa sem o bloco de mapa"


@pytest.mark.asyncio
async def test_os_tres_eventos_tem_variante_com_mapa(monkeypatch) -> None:
    monkeypatch.setattr(rota, "ClienteMeta", _ClienteFalso)

    # ⛔ O pânico saiu daqui em 10/09/2026: ele não leva cartão de mapa. Um
    # cartão com a posição atual também diz "estamos te vendo agora", e o
    # `PB-PANICO` manda a abertura ser uma checagem de rotina e nada mais.
    for codigo, esperado in [
        ("REMOCAO_BATERIA", "evento_alerta_pergunta_mapa"),
        ("MOVIMENTO_SEM_IGNICAO", "evento_alerta_pergunta_mapa"),
    ]:
        await rota._abrir_com_template(
            object(), _SessaoFalsa(codigo), _evento(latitude=-25.45, longitude=-49.25)
        )
        assert _ClienteFalso.ultimo["nome"] == esperado


def test_todo_evento_que_notifica_tem_as_duas_variantes() -> None:
    """Evento com modelo de texto e sem o de mapa cairia na reserva em silêncio.

    ⚠️ **Vale para o pânico também**, desde 10/09/2026: ele tem os quatro
    modelos, com a mesma cadeia. O que o distingue não é a estrutura, é o que
    o texto NÃO diz — isso está travado em `test_panico_chega_no_cliente`.
    """
    for codigo in rota.EVENTOS_QUE_NOTIFICAM:
        tipo = catalogo.por_codigo(codigo)
        assert tipo is not None, f"{codigo} notifica mas não está no catálogo"

        com_mapa = rota.templates_do_evento(
            tipo, _evento(latitude=-25.45, longitude=-49.25)
        )
        so_texto = rota.templates_do_evento(tipo, _evento())

        # Com coordenada sao quatro: geracao nova e reserva, cada uma com e sem
        # mapa. Sem coordenada sao duas, so as de texto.
        assert len(com_mapa) == 4, f"{codigo}: cadeia incompleta com coordenada"
        assert len(so_texto) == 2, f"{codigo}: cadeia incompleta sem coordenada"

        # As duas primeiras levam o cartao; as duas ultimas sao a rede.
        assert all(t[0].endswith("_mapa") for t in com_mapa[:2]), f"{codigo}: falta mapa"
        assert all(t[2] is not None for t in com_mapa[:2]), "modelo com mapa sem o bloco"
        assert not any(t[0].endswith("_mapa") for t in com_mapa[2:]), f"{codigo}: reserva com mapa"
        assert all(t[2] is None for t in so_texto), f"{codigo}: bloco de mapa sem coordenada"

        # ⛔ A ultima tentativa e sempre a geracao ANTERIOR, ja aprovada e ja
        # provada em producao. E ela que entrega enquanto a Meta analisa a nova.
        # So o nome: os dois eventos tem coordenadas diferentes, entao o Local
        # difere de proposito.
        assert com_mapa[-1][0] == so_texto[-1][0], f"{codigo}: a ultima nao e a reserva"


def test_evento_que_nao_notifica_nao_tem_tentativa() -> None:
    """A trava de `EVENTOS_QUE_NOTIFICAM`, vista de dentro.

    O modelo unificado serve qualquer tipo do catálogo, então a única coisa
    que impede um evento novo de virar mensagem para o cliente é esta lista.
    """
    tipo = catalogo.por_codigo("VELOCIDADE_EXCEDIDA")
    assert tipo is not None and tipo.elegivel_ia

    assert rota.templates_do_evento(tipo, _evento(latitude=-25.45, longitude=-49.25)) == []


# ─────────────────── a reserva quando o mapa falha em voo ───────────────────


class _ClienteQueRecusaMapa:
    """Recusa qualquer modelo `_mapa`, aceita o de texto.

    É o comportamento da Meta enquanto o modelo com mapa está `PENDING` — e
    também se ele for reprovado ou pausado por qualidade depois. Nenhum desses
    casos dá para prever na hora do envio.
    """

    tentativas: list[str] = []

    def __init__(self, cfg) -> None:  # noqa: ARG002
        pass

    async def enviar_template(self, para, nome, idioma="pt_BR", parametros=None, localizacao=None):
        _ClienteQueRecusaMapa.tentativas.append(nome)
        if nome.endswith("_mapa"):
            raise MetaIndisponivel("HTTP 400: template não aprovado")
        _ClienteFalso.ultimo = {
            "nome": nome,
            "parametros": parametros,
            "localizacao": localizacao,
        }
        return {"contacts": [{"wa_id": "5541999999999"}], "messages": [{"id": "wamid.T"}]}

    async def fechar(self) -> None:
        pass


@pytest.mark.asyncio
async def test_mapa_reprovado_cai_na_reserva_e_a_notificacao_sai(monkeypatch) -> None:
    """O caso que importa: o alarme chega mesmo quando o mapa não pode ir."""
    monkeypatch.setattr(rota, "ClienteMeta", _ClienteQueRecusaMapa)
    _ClienteQueRecusaMapa.tentativas = []

    ok = await rota._abrir_com_template(
        object(), _SessaoFalsa("REMOCAO_BATERIA"), _evento(latitude=-25.45, longitude=-49.25)
    )

    assert ok is True, "a notificação precisa sair mesmo sem o mapa"
    # ⚠️ Quatro tentativas, não duas: a geração com saudação e a reserva, cada
    # uma com e sem mapa. É esta cadeia que faz um modelo novo entrar sozinho
    # em produção quando a Meta aprova, sem deploy.
    # ⚠️ Tres tentativas, nao quatro: a terceira JA e sem mapa e por isso passa,
    # entao a reserva de texto nem chega a ser pedida. E o desenho funcionando —
    # a cadeia para na primeira que entrega.
    assert _ClienteQueRecusaMapa.tentativas == [
        "evento_alerta_pergunta_mapa",
        "evento_alerta_mapa",
        "evento_alerta_pergunta",
    ]
    # E o texto de reserva leva o Local: preenchido com a coordenada — aqui ela
    # é tudo o que existe, porque o cartão de mapa não foi.
    assert _ClienteFalso.ultimo["parametros"] == [
        # A abertura entrou como {{1}} em 10/09/2026. Sem `contato_nome` no
        # evento, ela e so a saudacao -- pela hora do EVENTO, nao a de agora.
        "bom dia",
        "Remoção de bateria",
        "ABC-1234",
        "09:00",
        "-25.45000, -49.25000",
    ]


class _ClienteQueRecusaTudo:
    def __init__(self, cfg) -> None:  # noqa: ARG002
        pass

    async def enviar_template(self, *args, **kwargs):
        raise MetaIndisponivel("HTTP 400: conta bloqueada")

    async def fechar(self) -> None:
        pass


@pytest.mark.asyncio
async def test_tudo_falhando_devolve_false_sem_explodir(monkeypatch) -> None:
    """Sem template não há abertura — mas a rota devolve 200 ao chamador."""
    monkeypatch.setattr(rota, "ClienteMeta", _ClienteQueRecusaTudo)

    ok = await rota._abrir_com_template(
        object(), _SessaoFalsa("REMOCAO_BATERIA"), _evento(latitude=-25.45, longitude=-49.25)
    )

    assert ok is False


# ─────────────── O que o cliente leu vira histórico da conversa ───────────────


@pytest.mark.asyncio
async def test_o_texto_entregue_e_registrado_para_as_duas_plateias(monkeypatch) -> None:
    """Sem isto o modelo não sabe que já falou, e o painel não mostra a abertura.

    Em 25/08/2026 um "Olá vou ver aqui" recebeu de volta uma apresentação e o
    evento recontado, palavra por palavra do que o motorista tinha acabado de
    ler. E, na tela do operador, a conversa começava pela resposta do cliente a
    uma mensagem que não aparecia em lugar nenhum.
    """
    monkeypatch.setattr(rota, "ClienteMeta", _ClienteFalso)
    sessao = _SessaoFalsa("REMOCAO_BATERIA")

    ok = await rota._abrir_com_template(
        object(), sessao, _evento(latitude=-25.45, longitude=-49.25)
    )

    assert ok is True

    # O modelo precisa do aviso de que aquilo já foi entregue e não é dele.
    para_o_modelo = sessao.historico[-1].conteudo
    assert "já entregue ao cliente" in para_o_modelo
    assert "no veículo *ABC-1234*" in para_o_modelo
    # Foi com mapa: ele precisa saber que o cartão de localização foi junto.
    assert "cartão de localização" in para_o_modelo

    # O operador vê o texto limpo, como apareceu no celular. Cabeçalho de
    # instrução na tela dele seria vazamento de andaime.
    do_painel = sessao.falas[-1]
    assert do_painel.tipo == "template"
    assert "no veículo *ABC-1234*" in do_painel.texto
    assert "já entregue ao cliente" not in do_painel.texto
    assert "não escrito por você" not in do_painel.texto

    # E os botões que a pessoa teve para tocar. Desde 26/08 eles abrem conversa
    # em vez de levar para a loja de aplicativos — botão de URL não devolve
    # webhook, e um "não respondeu" com esses botões na tela quer dizer outra
    # coisa do que queria com os antigos.
    assert do_painel.botoes == ["Preciso de ajuda!", "Está tudo bem!"]


@pytest.mark.asyncio
async def test_template_que_falhou_nao_e_registrado(monkeypatch) -> None:
    """O detalhe que faz a correção funcionar em vez de piorar as coisas.

    Template que não saiu não chegou a ninguém. Registrá-lo mesmo assim faria a
    IA responder a uma conversa que não aconteceu — e aí ela **deixaria** de se
    apresentar justamente na vez em que se apresentar é o certo. No painel,
    seria pior: mostraria ao operador uma mensagem que o cliente nunca recebeu.
    """
    monkeypatch.setattr(rota, "ClienteMeta", _ClienteQueRecusaTudo)
    sessao = _SessaoFalsa("REMOCAO_BATERIA")

    ok = await rota._abrir_com_template(
        object(), sessao, _evento(latitude=-25.45, longitude=-49.25)
    )

    assert ok is False
    assert sessao.falas == [], "mostrou ao operador uma mensagem que o cliente não recebeu"
    # O histórico nasce com o contexto da ocorrência; nada foi acrescentado.
    assert len(sessao.historico) == 1
