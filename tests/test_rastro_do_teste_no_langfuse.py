"""O que o Langfuse precisa saber sobre um disparo da tela de teste.

Pedido do Leonardo em 03/09/2026: *"precisa rastrear todas as mensagens que os
usuários utilizando pela tela de Enviar Eventos de Teste, incluindo qual modelo
foi selecionado de IA para responder o cliente, para assim avaliarmos depois e
corrigirmos os bugs"*.

⛔ **O Langfuse é o único lugar onde isso sobrevive.** A conversa e a trilha de
auditoria vivem em `SESSOES`, que é memória do processo, e o compose sobe a API
com `--reload`: salvar um `.py` durante um teste apaga o caso do painel. Quem
for avaliar depois vai ler o Langfuse, não a tela.

Duas coisas faltavam até aqui, e as duas quebravam justamente o "avaliarmos
depois":

* **`origem` não ia para o trace.** Teste e atendimento real somavam custo no
  mesmo lugar, e não havia como filtrar um dos dois.
* **A triagem não tinha span nenhum.** É a chamada mais cara do fluxo de pânico
  (`effort=high` sobre o resumo do veículo) e a que decide se haverá contato.
  Um pânico aparecia no Langfuse com o custo da conversa e sem o custo da
  decisão que autorizou a conversa. Quando ela falhava, o caso ia para a fila
  humana e não havia registro da chamada que falhou.
"""

from __future__ import annotations

import pytest

from central_ia.observability import tracing
from central_ia.observability.tracing import Identificacao


class SpanFalso:
    """Coleta os atributos, como o span real faria."""

    def __init__(self) -> None:
        self.atributos: dict[str, object] = {}

    def set_attribute(self, chave: str, valor: object) -> None:
        self.atributos[chave] = valor


class TracerFalso:
    def __init__(self) -> None:
        self.spans: list[SpanFalso] = []
        self.nomes: list[str] = []

    def start_as_current_span(self, nome: str):
        from contextlib import contextmanager

        @contextmanager
        def _abrir():
            span = SpanFalso()
            self.spans.append(span)
            self.nomes.append(nome)
            yield span

        return _abrir()


@pytest.fixture
def tracer(monkeypatch) -> TracerFalso:
    """Liga o tracing sem rede. `_conteudo` fechado é o pior caso de propósito.

    ⚠️ Em produção a porta de conteúdo é `False` sem exceção, e é lá que a
    marca de origem mais precisa funcionar: sem conteúdo, ela é uma das poucas
    coisas que ainda dá para filtrar.
    """
    falso = TracerFalso()
    monkeypatch.setattr(tracing, "_tracer", falso)
    monkeypatch.setattr(tracing, "_conteudo", False)
    return falso


QUEM_TESTE = Identificacao(ocorrencia="OC-2026-09-03-AAAA-WA", turno=1, origem="teste")
QUEM_REAL = Identificacao(ocorrencia="OC-2026-09-03-BBBB-WA", turno=1, origem="link")


# ─────────────────── a marca de origem no turno da IA ───────────────────


def test_o_turno_leva_a_origem_para_o_langfuse(tracer: TracerFalso) -> None:
    with tracing.span_do_turno("REMOCAO_BATERIA", "TEXTO", QUEM_TESTE):
        pass

    a = tracer.spans[0].atributos
    assert a["atendimento.origem"] == "teste"
    assert a["langfuse.trace.metadata.origem"] == "teste", "é por este que se filtra"


def test_a_origem_sai_mesmo_com_a_porta_de_conteudo_fechada(tracer: TracerFalso) -> None:
    """⛔ A asserção que importa para produção.

    Lá `langfuse_com_conteudo` é `False` sem exceção, e telefone, nome e placa
    não saem. Se a origem tivesse ido para dentro de `_identificar`, ela sumiria
    exatamente onde é a única pista que resta.
    """
    with tracing.span_do_turno("PANICO", "TEXTO", QUEM_TESTE):
        pass

    a = tracer.spans[0].atributos
    assert a["atendimento.origem"] == "teste"
    assert "langfuse.user.id" not in a, "dado pessoal continua barrado"


def test_o_nome_do_trace_agrupa_os_testes(tracer: TracerFalso) -> None:
    """O prefixo vem antes de tudo, e é de propósito.

    A lista do Langfuse ordena por nome, então `teste.` junta os ensaios num
    bloco em vez de espalhá-los entre os atendimentos reais. Quem for avaliar
    qualidade lê os de verdade sem tropeçar nos nossos.
    """
    with tracing.span_do_turno("PANICO", "TEXTO", QUEM_TESTE):
        pass

    assert tracer.spans[0].atributos["langfuse.trace.name"].startswith("teste.")


def test_evento_real_nao_ganha_prefixo(tracer: TracerFalso) -> None:
    """⚠️ `link` é o padrão e não entra no nome.

    Prefixar tudo faria o rótulo crescer sem separar nada, e a POC inteira
    apareceria como `link.atendimento.*`.
    """
    with tracing.span_do_turno("PANICO", "TEXTO", QUEM_REAL):
        pass

    nome = tracer.spans[0].atributos["langfuse.trace.name"]
    assert nome.startswith("atendimento."), nome


def test_a_ocorrencia_amarra_tudo_na_mesma_conversa(tracer: TracerFalso) -> None:
    """`session.id` é o que faz N spans aparecerem como uma conversa só."""
    with tracing.span_do_turno("PANICO", "TEXTO", QUEM_TESTE):
        pass

    assert tracer.spans[0].atributos["langfuse.session.id"] == QUEM_TESTE.ocorrencia


# ─────────────────────── o span novo da triagem ───────────────────────


def test_a_triagem_agora_tem_span(tracer: TracerFalso) -> None:
    """⛔ Era a maior cegueira do tracing até 03/09/2026.

    A triagem roda com `effort=high` sobre o resumo inteiro do veículo: é a
    chamada mais cara do fluxo de pânico, e a que decide se o cliente é
    contatado. Ela acontecia fora de qualquer span.
    """
    with tracing.span_da_triagem("PANICO", QUEM_TESTE):
        pass

    assert tracer.nomes == ["atendimento.triagem"]
    a = tracer.spans[0].atributos
    assert a["langfuse.observation.type"] == "generation", "para custo e tokens caírem certo"
    assert a["atendimento.origem"] == "teste"


def test_a_triagem_cai_na_mesma_conversa_do_atendimento(tracer: TracerFalso) -> None:
    """Mesma `session.id`, então ela aparece **antes** dos turnos.

    É a ordem em que aconteceu, e é o que permite ler "a triagem decidiu X, e
    aí a conversa foi assim" em vez de dois traces que não se conhecem.
    """
    with tracing.span_da_triagem("PANICO", QUEM_TESTE):
        pass
    with tracing.span_do_turno("PANICO", "TEXTO", QUEM_TESTE):
        pass

    sessoes = {s.atributos["langfuse.session.id"] for s in tracer.spans}
    assert sessoes == {QUEM_TESTE.ocorrencia}, "os dois spans, uma conversa"


def test_o_trace_da_triagem_se_distingue_do_turno(tracer: TracerFalso) -> None:
    """Nomes diferentes, senão não dá para saber qual span é qual na lista."""
    with tracing.span_da_triagem("PANICO", QUEM_TESTE):
        pass

    assert "triagem" in tracer.spans[0].atributos["langfuse.trace.name"]


# ─────────────────── quem gastou, registrado nos dois ───────────────────


def test_o_modelo_vai_com_os_nomes_que_o_langfuse_le(tracer: TracerFalso) -> None:
    """⚠️ Três atributos para o mesmo valor, e cada um tem dono.

    `llm.modelo` é nosso (painel de Jaeger montado nele não pode quebrar);
    `gen_ai.request.model` é a convenção do OpenTelemetry;
    `langfuse.observation.model.name` é o que o Langfuse lê para mostrar o
    modelo na coluna. Sem o terceiro, o trace chega sem modelo na tela.
    """
    with tracing.span_do_turno("PANICO", "TEXTO", QUEM_TESTE) as observado:
        observado.registrar(modelo="google/gemini-2.5-flash-lite", custo_usd=0.0016)

    a = tracer.spans[0].atributos
    for chave in ("llm.modelo", "gen_ai.request.model", "langfuse.observation.model.name"):
        assert a[chave] == "google/gemini-2.5-flash-lite", chave


def test_a_triagem_tambem_registra_o_modelo(tracer: TracerFalso) -> None:
    """Num pânico são dois modelos possíveis no mesmo caso, se alguém trocar no
    meio. Sem o modelo nos dois spans, não há como saber qual decidiu o quê."""
    with tracing.span_da_triagem("PANICO", QUEM_TESTE) as observado:
        observado.registrar(modelo="anthropic/claude-sonnet-5", custo_usd=0.004)

    assert (
        tracer.spans[0].atributos["langfuse.observation.model.name"]
        == "anthropic/claude-sonnet-5"
    )


def test_o_custo_sai_no_formato_que_o_langfuse_soma(tracer: TracerFalso) -> None:
    """Sem isto o trace chega e a coluna de custo fica vazia, que é metade do
    motivo de ter Langfuse."""
    with tracing.span_do_turno("PANICO", "TEXTO", QUEM_TESTE) as observado:
        observado.registrar(modelo="x", custo_usd=0.0745, tokens_entrada=20230, tokens_saida=600)

    a = tracer.spans[0].atributos
    assert "0.0745" in str(a["langfuse.observation.cost_details"])
    assert "20230" in str(a["langfuse.observation.usage_details"])


# ─────────────────── a triagem registra as duas tentativas ───────────────────


def test_a_triagem_registra_as_duas_tentativas(tracer: TracerFalso, monkeypatch) -> None:
    """⚠️ Registrar só a que deu certo esconderia o caso que queremos investigar.

    Quando a primeira falha por orçamento de tokens, a segunda roda com menos
    esforço. Um pânico que gastou duas chamadas para responder é exatamente o
    sintoma dos 9% de conversas mudas do Flash Lite — e sem as duas no span, ele
    aparece como um atendimento normal, só um pouco mais caro.
    """
    from central_ia.agent import triagem_panico
    from central_ia.ports.llm import OrcamentoDeTokensEstourado, RespostaLLM, Uso

    chamadas = {"n": 0}

    class ClienteFalso:
        async def gerar(self, **_kw):
            chamadas["n"] += 1
            if chamadas["n"] == 1:
                raise OrcamentoDeTokensEstourado("o raciocínio comeu o teto")
            return RespostaLLM(
                texto='{"probabilidade_real": 10, "classificacao": "falso_positivo",'
                ' "confianca": "alta", "evidencias": ["ignicao desligada"],'
                ' "justificativa": "Sem sinal de risco."}',
                modelo="google/gemini-2.5-flash-lite",
                uso=Uso(tokens_entrada=100, tokens_saida=50, custo_usd=0.001),
            )

        async def fechar(self) -> None:
            return None

    with tracing.span_da_triagem("PANICO", QUEM_TESTE) as observado:
        import asyncio

        _, custo = asyncio.run(
            triagem_panico.classificar(ClienteFalso(), {"resumo": "x"}, observado)
        )

    assert chamadas["n"] == 2, "a primeira falhou e a segunda rodou"
    assert custo == pytest.approx(0.001)
    # A tentativa fica no metadado: é assim que se mede a frequência disto.
    assert "tentativa-2" in str(tracer.spans[0].atributos["prompt.versao"])


def test_sem_span_a_triagem_nao_quebra(monkeypatch) -> None:
    """⛔ `observado=None` é o caminho de todo teste que já existia.

    A assinatura ganhou um parâmetro em 03/09/2026, e ele é opcional justamente
    para o tracing continuar sendo algo que se desliga sem afetar o fluxo.
    """
    from central_ia.agent import triagem_panico
    from central_ia.ports.llm import RespostaLLM, Uso

    class ClienteFalso:
        async def gerar(self, **_kw):
            return RespostaLLM(
                texto='{"probabilidade_real": 5, "classificacao": "falso_positivo",'
                ' "confianca": "alta", "evidencias": ["veiculo parado"],'
                ' "justificativa": "Sem sinal de risco."}',
                modelo="x",
                uso=Uso(tokens_entrada=1, tokens_saida=1, custo_usd=0.0),
            )

        async def fechar(self) -> None:
            return None

    import asyncio

    triagem, _ = asyncio.run(triagem_panico.classificar(ClienteFalso(), {"resumo": "x"}))

    assert triagem.probabilidade_real == 5
