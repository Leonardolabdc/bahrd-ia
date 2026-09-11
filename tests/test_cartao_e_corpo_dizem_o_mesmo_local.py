"""O endereço do cartão de mapa e o do corpo são o mesmo texto. Sempre.

⛔ **Pedido de 10/09/2026, olhando a mensagem chegar no celular.** O template
com mapa manda o endereço duas vezes: no rodapé do cartão de localização e na
linha `Local:` do corpo. Se os dois discordam, a mensagem se contradiz sobre
onde o caminhão está — e é a única informação da notificação que o motorista
não consegue conferir de cabeça.

E eles discordavam. Eram duas cascatas parecidas, escritas em lugares
diferentes:

    cartão:  endereco -> objeto_geografico -> "-25.45041, -49.25620"
    corpo:   endereco -> objeto_geografico -> "veja o mapa acima"

Nos dois primeiros degraus batiam por coincidência. No terceiro divergiam — e o
terceiro é **o caso normal**, porque o relatório da Bahrd traz a coluna
`Endereço` vazia e só manda coordenada.

⚠️ **A garantia agora é estrutural.** As duas pontas chamam `local_do_evento`,
então não existe segunda cascata para divergir da primeira. Estes testes
existem para o dia em que alguém "otimizar" copiando a lógica de volta para
dentro do `localizacao_do_evento`.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from central_ia.api.rotas.eventos import (
    local_do_evento,
    localizacao_do_evento,
    templates_do_evento,
)
from central_ia.domain import eventos as dom
from central_ia.integrations.mensageria import modelos
from central_ia.integrations.rastreamento.bahrd import EventoRastreamento


def _valor(nome: str, parametros: list[str], campo: str) -> str:
    """O parâmetro pelo NOME do campo, não pela posição.

    ⚠️ **A posição já mudou duas vezes num dia.** A abertura com saudação entrou
    na frente em 10/09/2026 e empurrou os quatro campos uma casa. Índice fixo
    aqui vira teste que quebra a cada campo novo — e, pior, teste que passa
    verde comparando o campo errado quando dois deles têm o mesmo valor.

    O manifesto declara a ordem, e é ele que o `enviar.ps1` publica: perguntar
    a ele é perguntar ao contrato.
    """
    ordem = modelos._manifesto()[nome]["parametros"]
    return parametros[ordem.index(campo)]

CURITIBA = (-25.4504094, -49.256198)


def _evento(**campos: object) -> EventoRastreamento:
    base: dict[str, object] = {
        "evento_externo_id": "x",
        "rotulo_link": "Remoção de bateria",
        "codigo_evento": "REMOCAO_BATERIA",
        "veiculo": "ABC1D23",
        "momento": datetime(2026, 9, 10, 12, 0, tzinfo=UTC),
        "latitude": CURITIBA[0],
        "longitude": CURITIBA[1],
    }
    return EventoRastreamento(**{**base, **campos})


#: Os três degraus da cascata, do melhor para o pior. O terceiro é o que
#: divergia, e é o que acontece em produção hoje.
CASOS = [
    pytest.param(
        {"endereco": "Rodovia Anhanguera, Americana - SP"},
        "Rodovia Anhanguera, Americana - SP",
        id="endereco-do-evento",
    ),
    pytest.param(
        {"objeto_geografico": "Pátio da Matriz"},
        "Pátio da Matriz",
        id="cerca-ou-ponto-de-interesse",
    ),
    pytest.param({}, "-25.45041, -49.25620", id="so-coordenada"),
]


@pytest.mark.parametrize(("campos", "esperado"), CASOS)
def test_o_cartao_e_o_corpo_carregam_o_mesmo_texto(
    campos: dict[str, object], esperado: str
) -> None:
    evento = _evento(**campos)

    cartao = localizacao_do_evento(evento)
    assert cartao is not None
    nome, parametros, _ = templates_do_evento(dom.REMOCAO_BATERIA, evento)[0]

    assert cartao["address"] == esperado
    assert _valor(nome, parametros, "local") == esperado


def test_a_placa_do_cartao_e_a_do_corpo_sao_a_mesma() -> None:
    """Mesmo raciocínio, para o outro dado que aparece nos dois lugares.

    O título do cartão é a placa, e o corpo repete no `Veículo:`. Duas placas
    diferentes na mesma mensagem fariam o motorista conferir o caminhão errado.
    """
    evento = _evento(veiculo="RST7U88")

    cartao = localizacao_do_evento(evento)
    assert cartao is not None
    nome, parametros, _ = templates_do_evento(dom.REMOCAO_BATERIA, evento)[0]

    assert cartao["name"] == "RST7U88"
    assert _valor(nome, parametros, "placa") == "RST7U88"


def test_a_reserva_sem_mapa_usa_o_mesmo_endereco() -> None:
    """⚠️ A variante de texto é a que entrega quando o modelo com mapa falha.

    Ela não tem cartão para comparar, mas tem que dizer a mesma coisa que o
    outro diria — senão o mesmo evento chega com endereços diferentes
    dependendo de qual dos dois modelos a Meta aceitou naquele instante.
    """
    evento = _evento(endereco="Rodovia Fernão Dias, Guarulhos - SP")

    tentativas = templates_do_evento(dom.REMOCAO_BATERIA, evento)

    # ⚠️ Todas as tentativas, e não só as duas primeiras: o mesmo evento não
    # pode chegar com endereços diferentes dependendo de qual modelo a Meta
    # aceitou naquele instante.
    assert len(tentativas) == 4
    for nome, parametros, _ in tentativas:
        assert _valor(nome, parametros, "local") == "Rodovia Fernão Dias, Guarulhos - SP"


def test_o_cartao_nunca_manda_endereco_vazio() -> None:
    """⛔ A Meta recusa o modelo inteiro se o `address` vier vazio.

    Custou um disparo real em 27/08/2026: «Parameter 'address' is mandatory for
    component parameter type 'location'». Sem cartão E sem reserva, o motorista
    não recebe nem o aviso do alarme.

    Como o cartão só existe quando há coordenada, `local_do_evento` sempre tem
    ao menos os números para devolver — mas isso é consequência de duas regras
    em arquivos diferentes, e por isso está travado aqui.
    """
    for campos in ({}, {"endereco": ""}, {"objeto_geografico": ""}):
        cartao = localizacao_do_evento(_evento(**campos))
        assert cartao is not None
        assert cartao["address"].strip(), f"address vazio com {campos}"


def test_sem_coordenada_nao_ha_cartao_para_divergir() -> None:
    """Sem mapa, sobra só o corpo — e ele continua respondendo pela cascata."""
    evento = _evento(latitude=None, longitude=None, endereco="Rua Comendador Roseira")

    assert localizacao_do_evento(evento) is None
    assert local_do_evento(evento) == "Rua Comendador Roseira"
