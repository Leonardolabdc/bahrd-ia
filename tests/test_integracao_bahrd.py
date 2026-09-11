"""Parser do evento da plataforma da Bahrd.

As três linhas têm a **forma exata** de um relatório real da plataforma —
ordem de chaves diferente entre linhas, `contador` presente em uma só, espaço
depois do parêntese no IMEI, unidade grudada no número, tipo de evento colado
ao nome da cerca. É isso que o parser precisa aguentar, e fixture inventada
esconde exatamente o que quebra em produção.

**Os valores foram trocados; o formato não.** Nome, IMEI, endereço e coordenada
são fictícios, porque dado pessoal de cliente não entra em repositório — e o
teste não perde nada com a troca, já que o que ele protege é a estrutura.

Se precisar conferir contra o original, ele está fora do versionamento:
`docs/exemplos/Relatorio de Eventos.xls`, veículo real, 12/08/2026 07:54.
"""

from __future__ import annotations

from datetime import UTC, datetime

from central_ia.integrations.rastreamento import bahrd

# ────────────── três linhas com a forma real, valores fictícios ──────────────

LINHA_9 = {
    "Grupo": "FROTA EXEMPLO",
    "Placa": "MOVEL GL 320 ( 860200000000000)",
    "Motorista": "",
    "Velocidade Atingida": "4.0 kmh",
    "Velocidade": "0 kmh",
    "Região": "",
    "Endereço": "Rua Comendador Roseira, Curitiba, PR, 80215-180, Brazil",
    "Latitude/Longitude": "-25.450000/-49.250000",
    "Data/Hora Posição": "12/08/2026 07:54:49",
    "Data/hora gravação": "12/08/2026 07:54:56",
    "Data/Hora finalizado": "12/08/2026 07:54:57",
    "Tipo Evento": "Entrou na cerca PATIO.MATRIZ.PONTO DE INTERESSE",
    "Observação": "",
    "Usuário": "dev",
    "Dados": (
        "velocidade: 4.0\ndirecao: 104\npanico: 0\nignicao: 1\n"
        "entradas: 0\nsaidas: 0\nhorimetro: 0\nodometro: 444 Km"
    ),
}

# Mesma entrada, gravada de novo pela plataforma: ordem das chaves trocada e
# um `contador` a mais.
LINHA_10 = {
    **LINHA_9,
    "Dados": (
        "direcao: 104\nvelocidade: 4.0\npanico: 0\nignicao: 1\n"
        "entradas: 0\nsaidas: 0\nhorimetro: 0\nodometro: 444 Km\ncontador: 19927"
    ),
}

LINHA_11 = {
    **LINHA_9,
    "Data/Hora finalizado": "12/08/2026 07:54:56",
    "Tipo Evento": "Voltou à Cerca de Polígono PATIO.MATRIZ.CERCA DE POLÍGONO",
}


def test_campos_principais_da_linha_real() -> None:
    evento = bahrd.parse_linha_relatorio(LINHA_9)

    assert evento.rotulo_link == "Entrou na cerca"
    assert evento.codigo_evento == "ENTROU_NA_CERCA"
    assert evento.objeto_geografico == "PATIO.MATRIZ.PONTO DE INTERESSE"
    assert evento.imei == "860200000000000"
    assert evento.veiculo == "MOVEL GL 320"
    assert evento.grupo == "FROTA EXEMPLO"
    assert evento.motorista is None
    assert evento.endereco == "Rua Comendador Roseira, Curitiba, PR, 80215-180, Brazil"


def test_horario_de_brasilia_vira_utc() -> None:
    """07:54:49 em Brasília é 10:54:49 UTC. Errar isso desloca a auditoria em 3 h."""
    evento = bahrd.parse_linha_relatorio(LINHA_9)

    assert evento.momento == datetime(2026, 8, 12, 10, 54, 49, tzinfo=UTC)
    assert evento.momento_gravacao == datetime(2026, 8, 12, 10, 54, 56, tzinfo=UTC)


def test_latitude_longitude_no_mesmo_campo() -> None:
    evento = bahrd.parse_linha_relatorio(LINHA_9)

    assert evento.latitude == -25.450000
    assert evento.longitude == -49.250000


def test_numeros_vem_com_unidade_grudada() -> None:
    evento = bahrd.parse_linha_relatorio(LINHA_9)

    assert evento.velocidade_kmh == 4.0        # "4.0 kmh"
    assert evento.velocidade_limite_kmh == 0.0  # "0 kmh"
    assert evento.odometro_km == 444.0          # "444 Km"
    assert evento.direcao == 104


def test_ordem_das_chaves_de_dados_nao_importa() -> None:
    """A linha 10 traz as mesmas chaves em outra ordem — e o resultado é igual."""
    nove = bahrd.parse_linha_relatorio(LINHA_9)
    dez = bahrd.parse_linha_relatorio(LINHA_10)

    assert nove.velocidade_kmh == dez.velocidade_kmh
    assert nove.direcao == dez.direcao
    assert nove.ignicao == dez.ignicao is True


def test_campo_opcional_ausente_nao_quebra() -> None:
    """`contador` só existe na linha 10."""
    assert bahrd.parse_linha_relatorio(LINHA_9).contador is None
    assert bahrd.parse_linha_relatorio(LINHA_10).contador == 19927


def test_zero_e_ausente_sao_coisas_diferentes() -> None:
    """`ignicao: 0` é informação; chave ausente é falta de informação."""
    com_zero = bahrd.parse_linha_relatorio({**LINHA_9, "Dados": "ignicao: 0"})
    sem_chave = bahrd.parse_linha_relatorio({**LINHA_9, "Dados": "velocidade: 4.0"})

    assert com_zero.ignicao is False
    assert sem_chave.ignicao is None


def test_payload_bruto_e_preservado_inteiro() -> None:
    """Campo que hoje não usamos é campo que amanhã explica um caso."""
    evento = bahrd.parse_linha_relatorio(LINHA_10)

    assert evento.bruto["contador"] == "19927"
    assert evento.bruto["odometro"] == "444 Km"


def test_duplicata_da_plataforma_colapsa() -> None:
    """As linhas 9 e 10 são a mesma entrada gravada duas vezes.

    Uma caminhada na cerca virou três eventos no relatório. Se isso passasse
    direto, o operador veria três ocorrências pelo mesmo fato.
    """
    eventos = [bahrd.parse_linha_relatorio(linha) for linha in (LINHA_9, LINHA_10, LINHA_11)]

    assert eventos[0].evento_externo_id == eventos[1].evento_externo_id
    assert eventos[2].evento_externo_id != eventos[0].evento_externo_id

    unicos = bahrd.deduplicar(eventos)
    assert len(unicos) == 2
    assert [e.rotulo_link for e in unicos] == ["Entrou na cerca", "Voltou à Cerca de Polígono"]


def test_id_e_estavel_entre_reprocessamentos() -> None:
    """Reimportar o mesmo relatório não pode criar ocorrência nova."""
    primeiro = bahrd.parse_linha_relatorio(LINHA_9)
    segundo = bahrd.parse_linha_relatorio(LINHA_9)

    assert primeiro.evento_externo_id == segundo.evento_externo_id


def test_evento_fora_do_catalogo_nao_entra_em_escopo() -> None:
    """Rótulo desconhecido volta inteiro, sem código — e nunca vira automático."""
    evento = bahrd.parse_linha_relatorio(
        {**LINHA_9, "Tipo Evento": "Sensor de fadiga acionado ALGUMA COISA"}
    )

    assert evento.codigo_evento is None
    assert evento.em_escopo is False
    assert evento.rotulo_link == "Sensor de fadiga acionado ALGUMA COISA"
    assert evento.objeto_geografico is None


def test_evento_sem_objeto_geografico() -> None:
    evento = bahrd.parse_linha_relatorio({**LINHA_9, "Tipo Evento": "Pânico"})

    assert evento.codigo_evento == "PANICO"
    assert evento.objeto_geografico is None


def test_linha_sem_data_de_posicao_e_recusada() -> None:
    """Sem o instante do evento não há como ordenar nem deduplicar."""
    import pytest

    with pytest.raises(ValueError, match="Data/Hora Posição"):
        bahrd.parse_linha_relatorio({**LINHA_9, "Data/Hora Posição": ""})
