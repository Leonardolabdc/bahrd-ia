"""O `Local:` da notificação, e a cascata que garante que ele nunca vá vazio.

Parâmetro vazio faz a Meta recusar o envio inteiro — a notificação não sai, e
o motorista não fica sabendo do alarme. Por isso a cascata termina sempre em
texto, nunca em `None`.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from central_ia.api.rotas.eventos import LOCAL_DESCONHECIDO, local_do_evento
from central_ia.integrations.rastreamento.bahrd import EventoRastreamento
from central_ia.integrations.rastreamento.bahrd_webhook import parse_evento_webhook


def _evento(**campos) -> EventoRastreamento:
    base = dict(
        evento_externo_id="x",
        rotulo_link="Remoção de bateria",
        codigo_evento="REMOCAO_BATERIA",
        veiculo="ABC-1234",
        momento=datetime(2026, 8, 24, 12, 0, tzinfo=UTC),
    )
    return EventoRastreamento(**{**base, **campos})


def test_endereco_ganha_de_tudo() -> None:
    evento = _evento(
        endereco="Rua Comendador Roseira, Curitiba - PR",
        objeto_geografico="Cerca Matriz",
        latitude=-25.45,
        longitude=-49.25,
    )

    assert local_do_evento(evento) == "Rua Comendador Roseira, Curitiba - PR"


def test_sem_endereco_usa_a_cerca() -> None:
    """Nome de cerca é texto que o cliente reconhece — melhor que coordenada."""
    evento = _evento(objeto_geografico="Pátio da Matriz", latitude=-25.45, longitude=-49.25)

    assert local_do_evento(evento) == "Pátio da Matriz"


def test_so_coordenada_vira_coordenada_legivel() -> None:
    evento = _evento(latitude=-25.4504094, longitude=-49.256198)

    assert local_do_evento(evento) == "-25.45041, -49.25620"


def test_sem_nada_ainda_devolve_texto() -> None:
    """O caso que protege o envio: nunca devolver vazio."""
    assert local_do_evento(_evento()) == LOCAL_DESCONHECIDO
    assert local_do_evento(_evento()) != ""


def test_latitude_sem_longitude_nao_vira_meia_coordenada() -> None:
    """Meia coordenada não localiza nada e confunde mais que ajuda."""
    assert local_do_evento(_evento(latitude=-25.45)) == LOCAL_DESCONHECIDO


def test_webhook_aceita_endereco_quando_a_link_mandar() -> None:
    """Hoje a Bahrd não manda; o dia em que mandar não deve exigir deploy."""
    evento = parse_evento_webhook(
        {
            "rotulo": "Veículo ABC-1234",
            "data_hora_evento": "2026-08-24 12:00:00",
            "tipo_evento": "Remoção de bateria",
            "endereco": "Rua Comendador Roseira, Curitiba - PR",
        }
    )

    assert evento.endereco == "Rua Comendador Roseira, Curitiba - PR"
    assert local_do_evento(evento) == "Rua Comendador Roseira, Curitiba - PR"


def test_webhook_sem_endereco_continua_valido() -> None:
    evento = parse_evento_webhook(
        {
            "rotulo": "Veículo ABC-1234",
            "data_hora_evento": "2026-08-24 12:00:00",
            "tipo_evento": "Remoção de bateria",
            "latitude": -25.4504094,
            "longitude": -49.256198,
        }
    )

    assert evento.endereco is None
    assert local_do_evento(evento) == "-25.45041, -49.25620"


# ─────────── O logradouro, sob o nome que a Bahrd vier a usar ───────────


@pytest.mark.parametrize("chave", ["endereco", "logradouro", "endereco_completo", "address"])
def test_o_logradouro_e_lido_sob_qualquer_nome_conhecido(chave: str) -> None:
    """O nome do campo ainda não foi combinado com a TI da Bahrd.

    Hoje a plataforma não manda endereço e o `📍 Local:` sai como "veja o mapa
    acima". Quando ela mandar, o campo pode chegar com qualquer um destes
    nomes — e ler só `endereco` faria o logradouro ser descartado em silêncio,
    com a mensagem saindo bonita e ninguém sabendo que o dado estava lá.
    """
    evento = parse_evento_webhook(
        {
            "rotulo": "ABC-1234",
            "tipo_evento": "Remoção de bateria",
            "data_hora_evento": "2026-08-27 18:30:00",
            chave: "Rua Carlos Coelho Junior, 630 - Curitiba/PR",
        }
    )

    assert evento.endereco == "Rua Carlos Coelho Junior, 630 - Curitiba/PR"
    assert local_do_evento(evento) == "Rua Carlos Coelho Junior, 630 - Curitiba/PR"


def test_logradouro_com_quebra_de_linha_e_higienizado() -> None:
    """Vem de cadastro, e cadastro tem texto colado de qualquer lugar.

    Um `\n` aqui faria a Meta recusar o parâmetro, e recusar o parâmetro é
    recusar a notificação inteira.
    """
    evento = parse_evento_webhook(
        {
            "rotulo": "ABC-1234",
            "tipo_evento": "Remoção de bateria",
            "data_hora_evento": "2026-08-27 18:30:00",
            "logradouro": "Rua Comendador Roseira\nCuritiba - PR",
        }
    )

    assert evento.endereco == "Rua Comendador Roseira Curitiba - PR"
    assert "\n" not in evento.endereco
