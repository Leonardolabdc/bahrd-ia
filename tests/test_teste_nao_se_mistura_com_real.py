"""Um evento de teste tem que ser impossível de confundir com um de verdade.

⛔ **Sem esta marca a tela de eventos de teste vira fonte de incidente.** Um
pânico disparado para experimentar cai na mesma fila, com a mesma cara, do
pânico de um motorista com uma arma apontada. Quem está de plantão às três da
manhã não tem como saber a diferença, e pode acionar apoio por causa de um
teste. Esse é o dano, e ele é maior que o custo da mensagem.

O segundo dano é mais lento e igualmente ruim: teste somado à métrica faz a taxa
de resolução da IA virar ficção, e a POC é julgada por esse número.

A marca nasce de **quem chamou**, nunca do corpo do evento. Pôr um campo
`teste: true` dentro do payload seria pedir para alguém falsificá-lo, e o parser
guarda campo desconhecido em `bruto` sem reclamar. Quem prova identidade com o
token do painel é que carimba.
"""

from __future__ import annotations

import pytest

from central_ia.domain import eventos
from central_ia.orchestration.sessao_whatsapp import SESSOES

BATERIA = eventos.por_codigo("REMOCAO_BATERIA")


@pytest.fixture(autouse=True)
def limpar():
    SESSOES.limpar()
    yield
    SESSOES.limpar()


def test_o_padrao_e_evento_real() -> None:
    """Quem não disse nada veio da Bahrd. O caminho de produção não muda."""
    assert SESSOES.abrir("+5541999999999", BATERIA, "TEXTO", {}).origem == "link"


def test_o_disparo_de_teste_fica_marcado() -> None:
    sessao = SESSOES.abrir("+5541999999999", BATERIA, "TEXTO", {}, origem="teste")

    assert sessao.origem == "teste"


def test_a_marca_chega_na_fila_do_operador() -> None:
    """De nada adianta marcar se a marca não sai na tela de quem está de plantão."""
    from central_ia.api.rotas.painel import _item_da_sessao

    sessao = SESSOES.abrir("+5541999999999", BATERIA, "TEXTO", {}, origem="teste")

    assert _item_da_sessao(sessao).origem == "teste"


def test_a_marca_aparece_na_ficha_da_ocorrencia() -> None:
    """Quem abre o caso vê de onde ele veio, sem precisar ler a trilha inteira."""
    from central_ia.api.rotas.painel import _ocorrencia_da_sessao

    sessao = SESSOES.abrir("+5541999999999", BATERIA, "TEXTO", {}, origem="teste")

    assert "Origem" in _ocorrencia_da_sessao(sessao).ficha


def test_evento_real_nao_ganha_linha_de_origem() -> None:
    """⚠️ A ficha do caso real não pode encher de campo que só serve para teste.

    Quem atende cliente de verdade lê essa ficha sob pressão. Linha a mais que
    sempre diz a mesma coisa é ruído que compete com o que importa.
    """
    from central_ia.api.rotas.painel import _ocorrencia_da_sessao

    sessao = SESSOES.abrir("+5541999999999", BATERIA, "TEXTO", {})

    assert "Origem" not in _ocorrencia_da_sessao(sessao).ficha


def test_a_ficha_diz_qual_ia_atendeu() -> None:
    """⚠️ Com a Central podendo trocar de modelo, é a primeira pergunta.

    O valor existia e ia só para o span de tracing: a ficha mostrava o custo e
    escondia quem tinha gastado. Comparar dois modelos sem saber qual atendeu
    cada caso não é comparação, é impressão.
    """
    from central_ia.api.rotas.painel import _ocorrencia_da_sessao

    sessao = SESSOES.abrir(
        "+5541999999999", BATERIA, "TEXTO", {}, modelo="anthropic/claude-sonnet-5"
    )

    assert _ocorrencia_da_sessao(sessao).ficha["IA"] == "anthropic/claude-sonnet-5"


# ─────────────────── a localização é a do evento ───────────────────


def test_logradouro_e_coordenada_sao_linhas_separadas() -> None:
    """⚠️ Vieram juntas numa linha só e o `ruff` reprovou por passar de 100
    caracteres — sintoma certo de um problema de leitura.

    O texto do logradouro já traz o estado do veículo ("acostamento, ignição
    desligada"), e a coordenada virava um terceiro trecho depois do terceiro
    `·`. Separadas, cada uma responde a sua pergunta, e a coordenada fica numa
    linha inteira que se seleciona de uma vez.
    """
    from central_ia.api.rotas.painel import _ocorrencia_da_sessao

    sessao = SESSOES.abrir("+5541999999999", BATERIA, "TEXTO", {})
    sessao.endereco = "Rodovia Anhanguera, Americana - SP"
    sessao.latitude = -25.4504094
    sessao.longitude = -49.256198
    ficha = _ocorrencia_da_sessao(sessao).ficha

    assert ficha["Logradouro"] == "Rodovia Anhanguera, Americana - SP"
    assert ficha["Coordenada"] == "-25.45041, -49.25620"


def test_so_a_coordenada_ainda_serve() -> None:
    """⚠️ É o caso **normal** em produção, não a exceção.

    O relatório da Bahrd traz `Latitude/Longitude` sempre e a coluna `Endereço`
    vem vazia (doc 14 §5). Exigir o logradouro para mostrar a posição a
    esconderia justamente no fluxo que roda de verdade.
    """
    from central_ia.api.rotas.painel import _ocorrencia_da_sessao

    sessao = SESSOES.abrir("+5541999999999", BATERIA, "TEXTO", {})
    sessao.latitude = -25.4504094
    sessao.longitude = -49.256198
    ficha = _ocorrencia_da_sessao(sessao).ficha

    assert ficha["Coordenada"] == "-25.45041, -49.25620"
    assert "Logradouro" not in ficha, "linha vazia não vira rótulo"


def test_sem_posicao_as_duas_linhas_somem() -> None:
    """Rótulo com travessão do lado ocupa espaço para dizer "não sei"."""
    from central_ia.api.rotas.painel import _ocorrencia_da_sessao

    ficha = _ocorrencia_da_sessao(
        SESSOES.abrir("+5541999999999", BATERIA, "TEXTO", {})
    ).ficha

    assert "Logradouro" not in ficha
    assert "Coordenada" not in ficha


def test_a_situacao_deixou_de_se_chamar_estado() -> None:
    """"Estado" numa tela de frota lê-se como unidade federativa antes de
    "situação do atendimento", ainda mais colado a uma placa."""
    from central_ia.api.rotas.painel import _ocorrencia_da_sessao

    ficha = _ocorrencia_da_sessao(
        SESSOES.abrir("+5541999999999", BATERIA, "TEXTO", {})
    ).ficha

    assert "Situação" in ficha
    assert "Estado" not in ficha
