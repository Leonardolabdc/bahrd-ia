"""A Central troca o cérebro que atende o cliente, e a troca vale da próxima conversa.

Pedido da operação: *"o seletor de selecionar o modelo precisa
trocar o modelo somente na próxima conversa, para caso as respostas aos clientes
estejam ruins alguém da central pode trocar o modelo que responde no whats do
cliente para assim melhorar a resposta ao cliente"*.

Não é um escopo de teste, é **controle de operação**: quem está de plantão vendo
a IA responder mal troca o cérebro sem esperar deploy.

⛔ **O que torna isso seguro é uma linha só:** `Sessao.modelo`, carimbado na
abertura. Sem ele o modelo seria lido do `cfg` a cada turno, e como `settings()`
é instância única e mutável, a troca pegaria conversas de cliente real no meio
de um turno: triagem decidida por um modelo, condução por outro, e nada na tela
dizendo. Estes testes existem para essa linha não sumir numa limpeza futura.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from central_ia.api.main import criar_app
from central_ia.config import Settings, settings
from central_ia.domain import eventos
from central_ia.integrations.llm import construir_cliente_llm
from central_ia.orchestration.sessao_whatsapp import SESSOES

SONNET = "anthropic/claude-sonnet-5"
FLASH_LITE = "google/gemini-2.5-flash-lite"
FLASH = "google/gemini-2.5-flash"
BATERIA = eventos.por_codigo("REMOCAO_BATERIA")


@pytest.fixture(autouse=True)
def limpar():
    SESSOES.limpar()
    yield
    SESSOES.limpar()
    settings.cache_clear()


@pytest.fixture
def cliente(monkeypatch) -> TestClient:
    monkeypatch.setenv("PAINEL_TESTES_ATIVO", "true")
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_MODELO", SONNET)
    monkeypatch.setenv("OPENROUTER_API_KEY", "chave-de-teste")
    monkeypatch.delenv("PAINEL_TOKEN", raising=False)
    settings.cache_clear()
    return TestClient(criar_app())


# ─────────────────────── o carimbo na abertura ───────────────────────


def test_a_sessao_nasce_com_o_cerebro_carimbado() -> None:
    sessao = SESSOES.abrir("+5541999999999", BATERIA, "TEXTO", {}, modelo=SONNET)

    assert sessao.modelo == SONNET


def test_conversa_em_curso_nao_troca_de_cerebro(cliente: TestClient) -> None:
    """⛔ A asserção que dá sentido a tudo isto.

    Quem já está falando com a IA termina no modelo em que começou. Trocar no
    meio deixaria a conversa quimera e ninguém saberia, porque a ficha da
    ocorrência mostraria um modelo só.
    """
    antiga = SESSOES.abrir("+5541999999999", BATERIA, "TEXTO", {}, modelo=SONNET)

    cliente.post("/painel/testes/modelo", json={"modelo": FLASH_LITE})

    assert antiga.modelo == SONNET, "a conversa aberta ficou onde estava"
    assert settings().modelo_em_uso == FLASH_LITE, "e o padrão mudou"


def test_a_proxima_conversa_nasce_no_cerebro_novo(cliente: TestClient) -> None:
    cliente.post("/painel/testes/modelo", json={"modelo": FLASH_LITE})
    nova = SESSOES.abrir(
        "+5541988887777", BATERIA, "TEXTO", {}, modelo=settings().modelo_em_uso
    )

    assert nova.modelo == FLASH_LITE


def test_o_cliente_de_llm_obedece_a_sessao(cliente: TestClient) -> None:
    """O carimbo só vale se alguém o ler. Este é o elo que costuma sumir."""
    cliente.post("/painel/testes/modelo", json={"modelo": FLASH_LITE})
    cfg = settings()

    assert construir_cliente_llm(cfg, SONNET).modelo == SONNET, "a sessão manda"
    assert construir_cliente_llm(cfg, None).modelo == FLASH_LITE, "sem sessão, o padrão"


def test_modelo_vazio_cai_no_padrao_e_nao_em_string_vazia(cliente: TestClient) -> None:
    """⛔ `""` iria parar no campo `model` do payload e voltaria como erro do
    provedor, não como configuração ausente."""
    assert construir_cliente_llm(settings(), "").modelo == SONNET


# ─────────────────────────── a trava do enum ───────────────────────────


def test_modelo_fora_da_lista_nao_passa(cliente: TestClient) -> None:
    """⛔ String livre daria acesso ao catálogo inteiro da OpenRouter.

    `ClienteOpenRouter` joga o valor direto no campo `model` do payload. Sem o
    `Literal`, alguém escolheria um modelo de US$ 75 por milhão de tokens, e a
    conta viria no fim do mês sem ninguém saber de onde.
    """
    resposta = cliente.post(
        "/painel/testes/modelo", json={"modelo": "openai/o3-pro"}
    )

    assert resposta.status_code == 422
    assert settings().modelo_em_uso == SONNET, "e nada mudou"


def test_a_troca_nao_existe_com_a_tela_desligada(monkeypatch) -> None:
    monkeypatch.setenv("PAINEL_TESTES_ATIVO", "false")
    monkeypatch.delenv("PAINEL_TOKEN", raising=False)
    settings.cache_clear()
    c = TestClient(criar_app())

    assert c.post("/painel/testes/modelo", json={"modelo": FLASH_LITE}).status_code == 404


# ─────────────────── o que a tela precisa dizer em voz alta ───────────────────


def test_a_reprovacao_do_flash_lite_continua_registrada(cliente: TestClient) -> None:
    """⚠️ **A tela deixou de dizer isto em 03/09/2026, a pedido da operação.**

    Saíram, em três pedidos seguidos: o selo "não aprovado para produção", o
    resumo e os dois defeitos medidos (tratou possível roubo como rotina; 9% das
    conversas morreram mudas, uma delas depois de o cliente pedir para falar com
    uma pessoa — docs/arquivo/26).

    O campo fica no contrato como registro da decisão, e este teste existe para
    ele não ser apagado junto por parecer sobra. Quem for reavaliar o modelo
    precisa achar o "não" em algum lugar.
    """
    disponiveis = cliente.get("/painel/testes/modelo").json()["disponiveis"]
    por_id = {m["id"]: m for m in disponiveis}

    assert por_id[FLASH_LITE]["aprovado_para_producao"] == "não"
    assert por_id[SONNET]["aprovado_para_producao"] == "sim"


def test_a_orientacao_e_o_que_sobrou_avisando(cliente: TestClient) -> None:
    """⛔ Com os defeitos fora da tela, é o único aviso que a pessoa lê.

    Ele diz o mesmo pelo lado de quem observa, e não pelo de quem mediu: "a IA
    conduzindo mal ou parando de responder" são exatamente os sintomas dos dois
    defeitos que saíram. Se esta frase sumir também, a tela passa a oferecer os
    dois modelos como equivalentes, diferentes só no preço.
    """
    orientacao = cliente.get("/painel/testes/modelo").json()["orientacao"]

    assert "mais barato" in orientacao
    assert "Sonnet 5" in orientacao
    assert "parando de responder" in orientacao


def test_a_versao_curta_diz_a_mesma_coisa(cliente: TestClient) -> None:
    """⚠️ Duas frases para a mesma política, e é aí que elas divergem.

    A curta fica colada em "Modelo de IA" com o bloco fechado; a longa aparece
    quando alguém abre. Se uma for reescrita sem a outra, a tela passa a dar
    conselhos diferentes conforme o retrátil esteja aberto ou não, e ninguém
    percebe porque nunca se vê as duas ao mesmo tempo.
    """
    corpo = cliente.get("/painel/testes/modelo").json()

    assert corpo["orientacao_curta"], "o rótulo fechado precisa dizer quando abrir"
    assert len(corpo["orientacao_curta"]) < 60, "não cabe no rótulo se for longa"
    # As duas mandam trocar pelo mesmo sintoma: a IA respondendo mal.
    assert "responder" in corpo["orientacao_curta"]
    assert "responder" in corpo["orientacao"]


def test_cada_modelo_diz_o_custo_e_como_ele_se_compara(cliente: TestClient) -> None:
    """Número sozinho não decide nada para quem não tem o outro na cabeça."""
    disponiveis = cliente.get("/painel/testes/modelo").json()["disponiveis"]
    por_id = {m["id"]: m for m in disponiveis}

    assert all("por atendimento" in m["custo"] for m in disponiveis)
    assert "barato" in por_id[FLASH_LITE]["custo_comparativo"]

    # ⚠️ O template da Meta entra na conta dos dois, e é o que derruba a
    # diferença de 26x (a razão entre as partes de IA) para cerca de 3x. Mostrar
    # os 26x venderia uma economia que não existe no atendimento inteiro.
    for modelo in disponiveis:
        assert "template Meta" in modelo["custo_detalhe"]
        assert "0,035" in modelo["custo_detalhe"]


def test_a_lista_e_fechada_e_ordenada_do_barato_ao_caro(cliente: TestClient) -> None:
    """⛔ Fechada, porque `ClienteOpenRouter` joga o `id` direto no payload.

    E **ordenada**: a tela mostra na ordem que vier, e a orientação manda começar
    pelo mais barato e subir um degrau por vez. Lista fora de ordem transformaria
    essa instrução em algo que a tela contradiz.
    """
    ids = [m["id"] for m in cliente.get("/painel/testes/modelo").json()["disponiveis"]]

    assert ids == [FLASH_LITE, FLASH, SONNET]


def test_o_intermediario_nao_finge_ter_sido_medido(cliente: TestClient) -> None:
    """⚠️ **O Gemini 2.5 Flash entrou em 03/09/2026 sem nenhuma rodada real.**

    Os outros dois têm custo medido em conversa (54 e 55 conversas); o dele é
    derivado da tabela de preços do doc 06, ancorado no medido do Flash Lite.

    Duas honestidades que este teste guarda:

    * o custo diz **(estimado)** por extenso, para ninguém tratar o número como
      medição;
    * `aprovado_para_producao` é `"não testado"`, e não `"sim"` nem `"não"`.
      "Sim" seria mentir. "Não" seria condenar sem prova: o defeito que reprovou
      o Flash Lite (possível roubo tratado como rotina) não se prevê por preço,
      e este modelo nunca rodou o roteiro.
    """
    por_id = {
        m["id"]: m for m in cliente.get("/painel/testes/modelo").json()["disponiveis"]
    }

    assert por_id[FLASH]["aprovado_para_producao"] == "não testado"
    assert "estimado" in por_id[FLASH]["custo_detalhe"]

    # E os medidos continuam sem essa ressalva, senão ela perde o sentido.
    for medido in (FLASH_LITE, SONNET):
        assert "estimado" not in por_id[medido]["custo_detalhe"]


# ─────────────────────── por que mexer no Settings dá certo ───────────────────────


def test_o_settings_e_uma_instancia_so_e_mutavel() -> None:
    """A propriedade em que a troca inteira se apoia, verificada e não assumida.

    ⛔ E o motivo de **não** usar `settings.cache_clear()` aqui: ele constrói um
    `Settings` novo, e as corrotinas que dormem em `_vigiar_silencio` segurando
    o objeto antigo ficariam nele para sempre. Dois modelos vivos ao mesmo
    tempo, sem nada na tela dizendo.
    """
    assert settings() is settings()
    assert Settings.model_config.get("frozen") is not True

    antes = settings().llm_provider
    try:
        settings().llm_provider = "openrouter"
        assert settings().llm_provider == "openrouter"
    finally:
        settings().llm_provider = antes
