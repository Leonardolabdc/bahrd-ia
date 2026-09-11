"""O adaptador da WhatsApp Cloud API (doc 11).

Três coisas que estes testes guardam, e que quebram silenciosamente se alguém
mexer sem olhar:

* a assinatura é sobre o **corpo bruto** — reserializar o JSON invalida;
* o aperto de mão devolve o `hub.challenge` **puro**;
* status de entrega e leitura **não são fala do cliente**.
"""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from central_ia.integrations.mensageria.meta import (
    LIMITE_PARAMETRO,
    PARAMETRO_VAZIO,
    assinatura_valida,
    desafio,
    extrair,
    numero_para_whatsapp,
    parametro_seguro,
)

SEGREDO = "segredo-do-app"


def _assinar(corpo: bytes, segredo: str = SEGREDO) -> str:
    return "sha256=" + hmac.new(segredo.encode(), corpo, hashlib.sha256).hexdigest()


def _payload(mensagem: dict) -> dict:
    """O envelope de cinco níveis da Meta, com uma mensagem dentro."""
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "100000000000001",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"phone_number_id": "100000000000002"},
                            "messages": [mensagem],
                        },
                    }
                ],
            }
        ],
    }


# ─────────────────────────────── assinatura ───────────────────────────────


def test_assinatura_confere_sobre_o_corpo_bruto() -> None:
    corpo = b'{"object":"whatsapp_business_account"}'

    assert assinatura_valida(SEGREDO, corpo, _assinar(corpo))


def test_reserializar_o_json_invalida_a_assinatura() -> None:
    """A armadilha do doc 11 §6, presa por teste.

    O corpo tem de ser o que chegou. `json.dumps` de um dict equivalente muda
    espaçamento — e um byte a mais derruba o HMAC.
    """
    corpo = b'{"object":"whatsapp_business_account"}'
    assinatura = _assinar(corpo)
    reserializado = json.dumps(json.loads(corpo)).encode()

    assert reserializado != corpo
    assert not assinatura_valida(SEGREDO, reserializado, assinatura)


def test_segredo_errado_nao_passa() -> None:
    corpo = b'{"a":1}'

    assert not assinatura_valida("outro-segredo", corpo, _assinar(corpo))


@pytest.mark.parametrize("enviada", ["", "sha1=abc", "abc", "sha256=", "sha256=naohex"])
def test_assinatura_malformada_nao_passa(enviada: str) -> None:
    assert not assinatura_valida(SEGREDO, b'{"a":1}', enviada)


# ─────────────────────────────── aperto de mão ───────────────────────────────


def test_desafio_devolve_o_challenge() -> None:
    parametros = {
        "hub.mode": "subscribe",
        "hub.verify_token": "minha-frase",
        "hub.challenge": "1158201409",
    }

    assert desafio(parametros, "minha-frase") == "1158201409"


def test_desafio_com_token_errado_recusa() -> None:
    parametros = {
        "hub.mode": "subscribe",
        "hub.verify_token": "chute",
        "hub.challenge": "1158201409",
    }

    assert desafio(parametros, "minha-frase") is None


def test_desafio_sem_modo_subscribe_recusa() -> None:
    parametros = {"hub.verify_token": "minha-frase", "hub.challenge": "123"}

    assert desafio(parametros, "minha-frase") is None


# ─────────────────────────────── extração ───────────────────────────────


def test_extrai_mensagem_de_texto() -> None:
    payload = _payload(
        {
            "from": "5541988888888",
            "id": "wamid.ABC123",
            "type": "text",
            "text": {"body": "bateria"},
        }
    )

    (recebida,) = extrair(payload)

    assert recebida.de == "5541988888888"
    assert recebida.texto == "bateria"
    assert recebida.mensagem_id == "wamid.ABC123"
    assert not recebida.tem_audio


def test_extrai_audio() -> None:
    payload = _payload(
        {
            "from": "5541988888888",
            "id": "wamid.XYZ",
            "type": "audio",
            "audio": {"id": "media-999", "mime_type": "audio/ogg; codecs=opus"},
        }
    )

    (recebida,) = extrair(payload)

    assert recebida.tem_audio
    assert recebida.midia_id == "media-999"


def test_status_de_entrega_nao_e_fala_do_cliente() -> None:
    """Se virasse fala, a IA responderia ao próprio eco."""
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "statuses": [
                                {"id": "wamid.ABC", "status": "delivered", "recipient_id": "55419"}
                            ]
                        }
                    }
                ]
            }
        ]
    }

    assert extrair(payload) == []


def test_video_e_foto_chegam_em_vez_de_sumir() -> None:
    """O doc 07 registrou que hoje vídeo é ignorado em silêncio. Aqui não é."""
    payload = _payload(
        {
            "from": "5541988888888",
            "type": "video",
            "video": {"id": "media-1", "mime_type": "video/mp4", "caption": "olha isso"},
        }
    )

    (recebida,) = extrair(payload)

    assert recebida.de == "5541988888888"
    assert recebida.texto == "olha isso"
    assert not recebida.tem_audio


def test_lote_com_varias_mensagens() -> None:
    """A Meta manda em lote. Tratar só a primeira perde conversa."""
    payload = _payload({"from": "1", "type": "text", "text": {"body": "um"}})
    payload["entry"][0]["changes"][0]["value"]["messages"].append(
        {"from": "2", "type": "text", "text": {"body": "dois"}}
    )

    assert [m.texto for m in extrair(payload)] == ["um", "dois"]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"entry": []},
        {"entry": [{}]},
        {"entry": [{"changes": [{}]}]},
        {"entry": [{"changes": []}]},
    ],
)
def test_payload_torto_devolve_vazio_em_vez_de_explodir(payload: dict) -> None:
    """`KeyError` aqui derrubaria o canal inteiro."""
    assert extrair(payload) == []


def test_mensagem_sem_remetente_e_descartada() -> None:
    assert extrair(_payload({"type": "text", "text": {"body": "oi"}})) == []


# ─────────────────────────────── número ───────────────────────────────


@pytest.mark.parametrize(
    ("bruto", "esperado"),
    [
        ("+5541988888888", "5541988888888"),
        ("whatsapp:+5541988888888", "5541988888888"),
        ("5541988888888", "5541988888888"),
    ],
)
def test_numero_perde_o_mais_e_o_prefixo(bruto: str, esperado: str) -> None:
    """A Meta não usa `+` nem `whatsapp:` — o Twilio usa os dois."""
    assert numero_para_whatsapp(bruto) == esperado


# ────────────── O que cabe dentro de um `{{n}}` do modelo ──────────────


def test_quebra_de_linha_vira_espaco() -> None:
    """⚠️ O caso que derruba a notificação inteira.

    A Meta recusa parâmetro com quebra de linha, e recusar o parâmetro é
    recusar a mensagem. O conteúdo não é nosso: o `Local:` cai em cascata até
    o `objeto_geografico`, que é nome de cerca cadastrado por alguém na
    plataforma da Bahrd e pode ter vindo colado de qualquer lugar.

    Pior: as duas tentativas (mapa e texto) mandam o mesmo local, então as
    duas falhavam juntas — nem o mapa nem o aviso do alarme chegavam.
    """
    assert parametro_seguro("Pátio\nda Matriz") == "Pátio da Matriz"
    assert parametro_seguro("Rua A\r\n\tnº 30") == "Rua A nº 30"
    assert parametro_seguro("  espaço    demais  ") == "espaço demais"


def test_texto_longo_e_cortado_no_teto_da_meta() -> None:
    cortado = parametro_seguro("x" * (LIMITE_PARAMETRO + 500))

    assert len(cortado) == LIMITE_PARAMETRO
    assert cortado.endswith("…"), "o corte precisa aparecer para quem lê"


def test_texto_no_limite_passa_inteiro() -> None:
    """O teto é limite, não gatilho: exatamente 1024 não é longo demais."""
    exato = "x" * LIMITE_PARAMETRO

    assert parametro_seguro(exato) == exato


def test_vazio_nunca_sai_vazio() -> None:
    """Um traço é feio; não avisar que mexeram na bateria do caminhão é grave.

    A Meta recusa parâmetro em branco. Se o valor colapsar para nada — só
    espaço, só quebra de linha —, o traço mantém a notificação de pé.
    """
    assert parametro_seguro("") == PARAMETRO_VAZIO
    assert parametro_seguro("   \n\t  ") == PARAMETRO_VAZIO


def test_o_que_ja_esta_bom_nao_e_tocado() -> None:
    """Idempotente, e isso importa: a rota higieniza e o cliente HTTP também.

    Os dois precisam chegar ao mesmo valor, porque é com ele que
    `modelos.corpo()` reconstrói o texto que o cliente leu. Se a segunda
    passada mudasse algo, a IA "lembraria" de uma mensagem diferente da que
    saiu.
    """
    for valor in ["Remoção de bateria", "ABC-1234", "18:30", "Rua X, 30 - Curitiba"]:
        assert parametro_seguro(valor) == valor
        assert parametro_seguro(parametro_seguro(valor)) == valor


# ──────── O webhook e "pelo menos uma vez", nao "exatamente uma vez" ────────


def test_a_mesma_mensagem_so_e_atendida_uma_vez() -> None:
    """Duplicata real, 27/08/2026, no primeiro teste do botão de causa.

    O painel mostrou "Em manutenção" **duas vezes** vindo do cliente, e duas
    respostas da IA — cada uma custando um turno e uma chamada paga, e a
    segunda respondendo a uma pergunta que a primeira já tinha feito.

    A causa não foi o cliente tocar duas vezes: **a Meta reenvia tudo que não
    recebe `200` rápido**, e nós só devolvemos `200` depois de a IA responder,
    o que leva uns três segundos porque tem uma chamada de modelo no meio. Ela
    desiste de esperar e manda de novo.

    Responder `200` antes de processar seria a outra saída, e é pior: perderia
    a mensagem em qualquer falha nossa, porque a Meta já teria sido dispensada.
    Deduplicar pelo identificador dela é o certo — ele é único por mensagem e
    sobrevive ao reenvio justamente por ser o mesmo.
    """
    from central_ia.api.rotas import whatsapp as rota

    rota._VISTAS.clear()

    assert rota._ja_processada("wamid.ABC") is False, "a primeira precisa passar"
    assert rota._ja_processada("wamid.ABC") is True, "a segunda precisa ser barrada"
    assert rota._ja_processada("wamid.XYZ") is False, "outra mensagem não é duplicata"


def test_sem_identificador_deixa_passar() -> None:
    """Melhor atender duas vezes do que não atender.

    Mensagem sem `id` não deveria existir, mas se existir, barrá-la seria
    trocar um defeito visível — duas respostas — por um invisível: silêncio.
    """
    from central_ia.api.rotas import whatsapp as rota

    rota._VISTAS.clear()

    assert rota._ja_processada(None) is False
    assert rota._ja_processada("") is False


def test_a_memoria_de_duplicatas_nao_cresce_para_sempre() -> None:
    """Um `set` sem teto num processo que roda meses é vazamento lento.

    A Meta reenvia em segundos, não em horas: 500 cobre qualquer rajada, e o
    que sai é sempre o mais antigo.
    """
    from central_ia.api.rotas import whatsapp as rota

    rota._VISTAS.clear()
    for n in range(rota.LIMITE_DE_MENSAGENS_VISTAS + 50):
        rota._ja_processada(f"wamid.{n}")

    assert len(rota._VISTAS) == rota.LIMITE_DE_MENSAGENS_VISTAS
    assert "wamid.0" not in rota._VISTAS, "o mais antigo precisa sair primeiro"
    assert f"wamid.{rota.LIMITE_DE_MENSAGENS_VISTAS + 49}" in rota._VISTAS


def test_o_digitando_nao_e_uma_mensagem() -> None:
    """E por isso nao e cobrado.

    A Meta fatura por mensagem entregue. Confirmacao de leitura nao entrega
    nada, e o indicador pega carona nessa mesma chamada — o corpo tem `status:
    read`, nunca `type` de mensagem.

    Se alguem um dia trocar isto por um envio de texto "digitando...", o custo
    aparece na fatura e o teste aparece aqui antes.
    """
    import asyncio

    from central_ia.integrations.mensageria.meta import ClienteMeta

    enviado: dict = {}

    class _Cliente(ClienteMeta):
        def __init__(self) -> None:  # noqa: D107
            pass

        async def _postar(self, corpo):
            enviado.update(corpo)
            return {}

    asyncio.run(_Cliente().mostrar_digitando("wamid.ABC"))

    assert enviado["status"] == "read"
    assert enviado["typing_indicator"] == {"type": "text"}
    assert "type" not in enviado, "isto seria uma mensagem, e mensagem e cobrada"
    assert "text" not in enviado
