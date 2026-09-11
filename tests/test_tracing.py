"""Telemetria carrega metadado. Conteúdo passa por uma porta com duas travas.

Um backend de observabilidade recebe *toda* conversa com *todo* motorista.
É o fluxo de dado pessoal mais completo do sistema, e o que menos parece um —
por isso é o que passa despercebido numa revisão.

A conversa já é registrada na trilha de auditoria da ocorrência, sob controle
da Bahrd. Duplicar num trace é pagar duas vezes, em disco e em exposição, pela
mesma informação — sendo a segunda cópia a menos protegida.

**Mudança de 25/08/2026.** Depurar prompt sem ver o prompt é adivinhação, e o
Langfuse existe para isso. Abriu-se uma porta — e a regra virou mais estreita,
não mais larga: conteúdo sai apenas com `LANGFUSE_ENVIAR_CONTEUDO=true`, que
nasce `false`, e **nunca** em produção, onde nenhuma variável destrava.

Estes testes deixaram de perguntar "existe caminho para o conteúdo?" e passaram
a perguntar "o caminho que existe está trancado onde deve estar?". O dia em que
alguém precisar "só debugar uma coisinha" continua coberto: a coisinha é uma
variável de ambiente numa máquina de desenvolvimento, não uma linha de código
que sobe junto com o resto.
"""

from __future__ import annotations

import inspect
import json
from base64 import b64encode
from typing import Any

import pytest

from central_ia.config import Settings
from central_ia.observability import tracing
from central_ia.ports.llm import Mensagem

#: Conversa de mentira com a cara da de verdade: nome e placa. Se qualquer um
#: dos dois aparecer num span que não devia, o teste enxerga.
CONVERSA = [
    Mensagem(papel="system", conteudo="Ocorrência de remoção de bateria."),
    Mensagem(papel="user", conteudo="aqui é o João da Silva, placa ABC1D23"),
]
RESPOSTA_BRUTA = "Obrigada, João. Confirma a placa ABC1D23? [ESCALAR]"

#: O que não pode vazar, em qualquer forma.
PEGADAS = ("João", "ABC1D23")


def _cfg(**extra: Any) -> Settings:
    """Configuração mínima, com tudo de telemetria desligado por padrão.

    Explícito e não herdado do `.env`: um teste que muda de resultado conforme
    a máquina de quem roda não guarda nada.
    """
    base: dict[str, Any] = {
        "oracle_password": "x",
        "mysql_password": "x",
        "otel_exporter_otlp_endpoint": "",
        "langfuse_public_key": "",
        "langfuse_secret_key": None,
        "langfuse_enviar_conteudo": False,
    }
    return Settings(**{**base, **extra})


class ProvedorFalso:
    """Recolhe os processadores registrados, sem subir OpenTelemetry de verdade."""

    def __init__(self) -> None:
        self.processadores: list[Any] = []

    def add_span_processor(self, processador: Any) -> None:
        self.processadores.append(processador)


class SpanFalso:
    """Guarda o que foi anotado, para o teste inspecionar."""

    def __init__(self) -> None:
        self.atributos: dict[str, Any] = {}

    def set_attribute(self, chave: str, valor: Any) -> None:
        self.atributos[chave] = valor

    def tudo_em_texto(self) -> str:
        """Chaves e valores num texto só — para caçar vazamento em qualquer campo."""
        return json.dumps(self.atributos, ensure_ascii=False, default=str)


# ─────────────────────── A porta e as travas ───────────────────────


def test_porta_nasce_fechada() -> None:
    """Credencial configurada não implica conteúdo. São decisões separadas."""
    cfg = _cfg(langfuse_public_key="pk-lf-teste", langfuse_secret_key="sk-lf-teste")

    assert cfg.langfuse_ativo is True
    assert cfg.langfuse_com_conteudo is False


def test_porta_abre_em_desenvolvimento_com_pedido_explicito() -> None:
    cfg = _cfg(
        langfuse_public_key="pk-lf-teste",
        langfuse_secret_key="sk-lf-teste",
        langfuse_enviar_conteudo=True,
    )

    assert cfg.em_producao is False
    assert cfg.langfuse_com_conteudo is True


@pytest.mark.parametrize("ambiente", ["hml", "prd-poc"])
def test_producao_ignora_a_variavel(ambiente: str) -> None:
    """A segunda trava não tem chave.

    É o caso do esquecimento: alguém liga a variável para depurar, o `.env`
    viaja para o ambiente promovido, e ninguém lembra de desligar. Aqui isso
    não vaza nada.
    """
    cfg = _cfg(
        app_env=ambiente,
        langfuse_public_key="pk-lf-teste",
        langfuse_secret_key="sk-lf-teste",
        langfuse_enviar_conteudo=True,
    )

    assert cfg.em_producao is True
    assert cfg.langfuse_com_conteudo is False


def test_langfuse_exige_as_duas_chaves() -> None:
    """Meia credencial é erro de `.env`, não meio-modo."""
    assert _cfg(langfuse_public_key="pk-lf-teste").langfuse_ativo is False
    assert _cfg(langfuse_secret_key="sk-lf-teste").langfuse_ativo is False


# ─────────────────────── O que chega no span ───────────────────────


def test_conteudo_nao_sai_com_a_porta_fechada(monkeypatch: pytest.MonkeyPatch) -> None:
    """O centro de tudo.

    O chamador passa a conversa em todo ambiente — é a trava aqui que decide.
    Se esta asserção cair, conversa de motorista está indo para a nuvem.
    """
    monkeypatch.setattr(tracing, "_conteudo", False)
    span = SpanFalso()

    tracing.Turno(span).registrar(
        modelo="claude-x",
        tokens_entrada=10,
        custo_usd=0.01,
        entrada=CONVERSA,
        saida=RESPOSTA_BRUTA,
    )

    texto = span.tudo_em_texto()
    for pegada in PEGADAS:
        assert pegada not in texto, f"'{pegada}' vazou para o span com a porta fechada"
    assert "langfuse.observation.input" not in span.atributos
    assert "langfuse.observation.output" not in span.atributos
    # E o metadado continua indo — a trava fecha o conteúdo, não o resto.
    assert span.atributos["llm.modelo"] == "claude-x"


def test_conteudo_sai_com_a_porta_aberta(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tracing, "_conteudo", True)
    span = SpanFalso()

    tracing.Turno(span).registrar(modelo="claude-x", entrada=CONVERSA, saida=RESPOSTA_BRUTA)

    entrada = json.loads(span.atributos["langfuse.observation.input"])
    assert entrada[1] == {"role": "user", "content": "aqui é o João da Silva, placa ABC1D23"}
    # A resposta vai **bruta**, com as marcas de controle: é o `[ESCALAR]` no
    # lugar errado que se quer enxergar ao depurar.
    assert span.atributos["langfuse.observation.output"] == RESPOSTA_BRUTA


def test_uso_e_custo_no_formato_que_o_langfuse_le(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sem isto o trace chega sem custo e sem tokens — metade do motivo de ter Langfuse."""
    monkeypatch.setattr(tracing, "_conteudo", False)
    span = SpanFalso()

    tracing.Turno(span).registrar(
        modelo="claude-x",
        tokens_entrada=1200,
        tokens_saida=80,
        tokens_cache=900,
        custo_usd=0.0042,
    )

    assert json.loads(span.atributos["langfuse.observation.usage_details"]) == {
        "input": 1200,
        "output": 80,
        # Chave própria: a convenção `gen_ai.usage.*` não tem uma para cache, e
        # numa POC em que o cache é o que segura o custo, esse é o número.
        "cache_read_input_tokens": 900,
    }
    assert json.loads(span.atributos["langfuse.observation.cost_details"]) == {"total": 0.0042}
    assert span.atributos["gen_ai.request.model"] == "claude-x"
    # Os nomes antigos ficam: painel de Jaeger montado sobre eles não quebra.
    assert span.atributos["llm.tokens_cache"] == 900


def test_sem_numero_nenhum_nao_inventa_uso() -> None:
    assert tracing._uso_em_json(None, None, None) is None
    assert json.loads(tracing._uso_em_json(5, None, None) or "{}") == {"input": 5}


QUEM = tracing.Identificacao(
    ocorrencia="OC-2026-0001",
    telefone="+5541999999999",
    nome="Bruno da Silva",
    placa="ABC-1234",
)


def _tracer_falso(monkeypatch: pytest.MonkeyPatch) -> SpanFalso:
    """Liga um tracer de mentira e devolve o span que ele entrega."""
    from contextlib import contextmanager

    span = SpanFalso()

    class TracerFalso:
        @contextmanager
        def start_as_current_span(self, nome: str) -> Any:
            span.atributos["__nome_do_span__"] = nome
            yield span

    monkeypatch.setattr(tracing, "_tracer", TracerFalso())
    return span


def test_span_desligado_e_inerte() -> None:
    """Com tracing desligado, anotar não pode explodir — nem fazer nada."""
    with tracing.span_do_turno("REMOCAO_BATERIA", "TEXTO", QUEM) as observado:
        observado.registrar(modelo="x", custo_usd=0.01, entrada=CONVERSA, saida=RESPOSTA_BRUTA)


def test_sessao_agrupa_os_turnos_da_mesma_ocorrencia(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sem id de sessão, um atendimento vira N traces soltos.

    A diferença entre ler uma conversa e garimpar spans. O id é o da ocorrência
    — interno, já usado na trilha de auditoria, não é telefone nem placa, e por
    isso sai em qualquer ambiente.
    """
    monkeypatch.setattr(tracing, "_conteudo", False)
    span = _tracer_falso(monkeypatch)

    with tracing.span_do_turno("REMOCAO_BATERIA", "TEXTO", QUEM):
        pass

    assert span.atributos["langfuse.session.id"] == "OC-2026-0001"
    assert span.atributos["langfuse.observation.type"] == "generation"
    assert span.atributos["evento.tipo"] == "REMOCAO_BATERIA"


# ─────────────────────── Achar o atendimento depois ───────────────────────


def test_com_a_porta_aberta_o_trace_leva_o_primeiro_nome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`atendimento.REMOCAO_BATERIA.Bruno` — legível na lista, sem clicar.

    Vinte atendimentos do mesmo tipo com o mesmo rótulo não ajudam a achar
    nenhum. E é assim que a central se refere ao caso: "o do Bruno", não
    "a ocorrência OC-2026-08-25-3F2A-WA".
    """
    monkeypatch.setattr(tracing, "_conteudo", True)
    span = _tracer_falso(monkeypatch)

    with tracing.span_do_turno("REMOCAO_BATERIA", "TEXTO", QUEM):
        pass

    assert span.atributos["langfuse.trace.name"] == "atendimento.REMOCAO_BATERIA.Bruno"
    # Só o primeiro nome: sobrenome identifica melhor, e por isso não vai.
    assert "Silva" not in span.atributos["langfuse.trace.name"]

    # E os campos de busca, que é o que o Langfuse deixa filtrar.
    assert span.atributos["langfuse.user.id"] == "+5541999999999"
    assert span.atributos["langfuse.trace.metadata.nome"] == "Bruno da Silva"
    assert span.atributos["langfuse.trace.metadata.placa"] == "ABC-1234"


def test_com_a_porta_fechada_nao_sai_nome_nem_telefone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mesma tranca do conteúdo. Em produção, ninguém é identificável no trace."""
    monkeypatch.setattr(tracing, "_conteudo", False)
    span = _tracer_falso(monkeypatch)

    with tracing.span_do_turno("REMOCAO_BATERIA", "TEXTO", QUEM):
        pass

    assert span.atributos["langfuse.trace.name"] == "atendimento.REMOCAO_BATERIA"

    texto = span.tudo_em_texto()
    for pegada in ("Bruno", "Silva", "999999999", "ABC-1234"):
        assert pegada not in texto, f"'{pegada}' vazou com a porta fechada"

    # A ocorrência continua saindo: é identificador interno, não pessoa.
    assert span.atributos["langfuse.session.id"] == "OC-2026-0001"


def test_sem_nome_o_rotulo_volta_a_ser_so_o_tipo(monkeypatch: pytest.MonkeyPatch) -> None:
    """Evento sem interlocutor cadastrado não pode gerar `atendimento.TIPO.`"""
    monkeypatch.setattr(tracing, "_conteudo", True)
    span = _tracer_falso(monkeypatch)

    with tracing.span_do_turno("PANICO", "TEXTO", tracing.Identificacao(ocorrencia="OC-9")):
        pass

    assert span.atributos["langfuse.trace.name"] == "atendimento.PANICO"


# ─────────────────────── Contrato com o agente ───────────────────────


def test_registrar_nao_aceita_pessoa() -> None:
    """A assinatura continua sendo trava para tudo que não é a porta.

    `entrada` e `saida` são a porta, e passam pela trava de `_conteudo`. Nome,
    placa, telefone e endereço não têm porta nenhuma: não existe parâmetro onde
    encaixá-los, e criar um passa por revisão de código.
    """
    parametros = set(inspect.signature(tracing.Turno.registrar).parameters)

    proibidos = {
        "motorista",
        "placa",
        "telefone",
        "endereco",
        "interlocutor",
        "localizacao",
        "coordenada",
        "kwargs",
    }
    vazamento = parametros & proibidos
    assert not vazamento, f"parâmetro de dado pessoal em span: {vazamento}"


def test_o_agente_passa_a_conversa_mas_nao_decide_o_destino() -> None:
    """A decisão mora num lugar só.

    O agente chama igual em todo ambiente e `tracing` decide. Um `if` de
    ambiente aqui seria uma segunda regra, e duas regras divergem — sempre na
    direção errada, e sempre na semana em que ninguém está olhando.
    """
    from central_ia.agent import atendimento_real

    fonte = inspect.getsource(atendimento_real.proximo_turno)
    trecho = fonte.split("observado.registrar(", 1)[1].split("        )", 1)[0]

    assert "entrada=historico" in trecho
    assert "saida=bruto" in trecho

    codigo = [ln for ln in fonte.splitlines() if not ln.lstrip().startswith("#")]
    corpo = "\n".join(codigo)
    for decisao in ("em_producao", "langfuse", "app_env", "_conteudo"):
        assert decisao not in corpo, f"o agente está decidindo o destino com '{decisao}'"


# ─────────────────────── Como sai da aplicação ───────────────────────


def test_sem_endpoint_e_sem_langfuse_nao_liga_nada() -> None:
    """É o que mantém teste e máquina sem Jaeger funcionando sem erro."""
    assert tracing.configurar_tracing(_cfg()) is False


def test_langfuse_exporta_por_http_com_credencial() -> None:
    """O Langfuse não fala gRPC, e o exportador do Jaeger é gRPC.

    Este teste existe porque o erro seria silencioso: o `BatchSpanProcessor`
    engole a falha de exportação, o Jaeger continua recebendo tudo, e o
    Langfuse fica vazio sem ninguém saber por quê.
    """
    cfg = _cfg(langfuse_public_key="pk-lf-teste", langfuse_secret_key="sk-lf-teste")

    provedor = ProvedorFalso()
    tracing._ligar_langfuse(provedor, cfg)

    processador = provedor.processadores[0]
    exportador = processador.span_exporter
    try:
        assert "proto.http" in type(exportador).__module__, "gRPC não serve para o Langfuse"
        assert exportador._endpoint.endswith("/api/public/otel/v1/traces")

        cabecalhos = {c.lower(): v for c, v in exportador._session.headers.items()}
        credencial = b64encode(b"pk-lf-teste:sk-lf-teste").decode()
        assert cabecalhos["authorization"] == f"Basic {credencial}"
        # Sem o header de versão o evento cai no formato antigo, que já tem
        # data marcada para desligar.
        assert cabecalhos["x-langfuse-ingestion-version"] == "4"
    finally:
        processador.shutdown()


def test_os_dois_destinos_exportam_em_lote() -> None:
    """`SimpleSpanProcessor` exportaria dentro da requisição.

    Com ele, um coletor lento vira latência para quem está na estrada. Vale
    para os dois destinos, e o teste confere o objeto construído em vez de
    procurar o nome no código-fonte — o do Langfuse é uma subclasse, e
    procurar texto não enxergaria isso.
    """
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    grpc = ProvedorFalso()
    tracing._ligar_otlp_grpc(grpc, "http://otel:4317")

    http = ProvedorFalso()
    tracing._ligar_langfuse(
        http, _cfg(langfuse_public_key="pk-lf-teste", langfuse_secret_key="sk-lf-teste")
    )

    try:
        for provedor, destino in ((grpc, "Jaeger"), (http, "Langfuse")):
            processador = provedor.processadores[0]
            assert isinstance(processador, BatchSpanProcessor), f"{destino} exporta na requisição"
    finally:
        for provedor in (grpc, http):
            provedor.processadores[0].shutdown()


@pytest.mark.parametrize(
    "nome",
    [
        # Healthcheck do Docker a cada 15 s: ~172 mil traces/mês.
        "GET /saude/vivo",
        "GET /saude/pronto",
        # Polling do painel: quatro rotas a cada 3 s em tempo real. Sozinho
        # consome os 50 mil do plano grátis em dez horas de aba aberta.
        "GET /painel/estado",
        "GET /painel/fila",
        "GET /painel/desativados",
        "GET /painel/encerrados",
        # Protocolo ASGI. Medido nos traces reais: 65% a 75% de todos os spans
        # são estes, e são três unidades cobradas para transportar uma. Ficam no
        # Jaeger, onde mostram onde o tempo foi dentro do ASGI.
        "POST /whatsapp/meta http send",
        "POST /whatsapp/meta http receive",
        "POST /eventos/link http send",
    ],
)
def test_ruido_de_infra_nao_vai_para_o_langfuse(nome: str) -> None:
    """Medido em 25/08/2026, na primeira hora com o Langfuse ligado.

    Não é economia de centavo: é a diferença entre uma lista de traces onde se
    acha o atendimento e uma parede de polling onde ele some.
    """
    assert tracing._e_ruido_de_infra(nome) is True


@pytest.mark.parametrize(
    "nome",
    [
        "atendimento.turno",
        # As portas de entrada de um atendimento de verdade. O span do turno
        # pendura embaixo delas — filtrar aqui decapitaria o trace. Note que o
        # nome da rota é prefixo dos spans ASGI que o teste acima descarta: a
        # rota em si passa, o `http send` dela não.
        "POST /whatsapp/meta",
        "POST /eventos/link",
        # A ida ao modelo, instrumentada pelo httpx. É onde a latência do
        # OpenRouter aparece.
        "POST",
    ],
)
def test_atendimento_de_verdade_passa(nome: str) -> None:
    assert tracing._e_ruido_de_infra(nome) is False


def test_o_filtro_e_so_do_langfuse() -> None:
    """O Jaeger precisa do healthcheck: lá é local, ilimitado, e é o trabalho dele.

    Se um dia alguém "simplificar" excluindo a rota na instrumentação, o
    healthcheck some dos dois — e o Jaeger perde justamente o que monitora.
    """
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    grpc = ProvedorFalso()
    tracing._ligar_otlp_grpc(grpc, "http://otel:4317")

    http = ProvedorFalso()
    tracing._ligar_langfuse(
        http, _cfg(langfuse_public_key="pk-lf-teste", langfuse_secret_key="sk-lf-teste")
    )

    try:
        do_jaeger = type(grpc.processadores[0])
        do_langfuse = type(http.processadores[0])

        assert do_jaeger.on_end is BatchSpanProcessor.on_end, "o Jaeger perdeu o healthcheck"
        assert do_langfuse.on_end is not BatchSpanProcessor.on_end, "o Langfuse está sem filtro"
    finally:
        for provedor in (grpc, http):
            provedor.processadores[0].shutdown()


def test_instrumentacao_acontece_na_construcao_do_app() -> None:
    """`instrument_app` acrescenta middleware, e o Starlette congela a pilha.

    Chamado dentro do `lifespan`, o registro acontece tarde demais: nenhuma
    rota é traçada e **nenhum erro aparece**. O sintoma é silencioso — o
    Jaeger recebe span manual e nenhum de requisição.

    Custou uma sessão de diagnóstico. Este teste existe para custar zero da
    próxima vez.
    """
    from central_ia.api import main

    assert "configurar_tracing" in inspect.getsource(main.criar_app)
    assert "configurar_tracing" not in inspect.getsource(main.ciclo_de_vida)


# ─────────────────────── Aviso de entrega não é atendimento ───────────────────────


def test_requisicao_sem_conversa_nao_vai_para_o_langfuse(monkeypatch: pytest.MonkeyPatch) -> None:
    """**Medido em 25/08/2026: 57 dos últimos 100 traces eram isto.**

    `POST /whatsapp/meta` recebe duas coisas no mesmo endereço: a mensagem do
    motorista e os avisos de entrega da Meta. Um disparo produz três — enviado,
    entregue, lido —, os três no mesmo segundo, e cada um virava um trace vazio.

    Filtrar pelo nome da rota não serve: o span dela é a **raiz** do atendimento
    de verdade, com o turno da IA pendurado embaixo. Quem sabe distinguir é o
    código que leu o corpo, e é de lá que vem a marca.
    """
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provedor = ProvedorFalso()
    tracing._ligar_langfuse(
        provedor, _cfg(langfuse_public_key="pk-lf-teste", langfuse_secret_key="sk-lf-teste")
    )
    processador = provedor.processadores[0]

    class SpanDeAviso:
        name = "POST /whatsapp/meta"
        attributes = {tracing._SEM_ATENDIMENTO: False}

    class SpanDeAtendimento:
        name = "POST /whatsapp/meta"
        attributes = {"http.status_code": 200}

    try:
        enviados: list[str] = []
        monkeypatch.setattr(
            BatchSpanProcessor, "on_end", lambda self, span: enviados.append(span.name)
        )

        processador.on_end(SpanDeAviso())
        assert enviados == [], "aviso de entrega vazou para o Langfuse"

        processador.on_end(SpanDeAtendimento())
        assert enviados == ["POST /whatsapp/meta"], "a raiz do atendimento foi decapitada"
    finally:
        processador.shutdown()


def test_marcar_e_inerte_com_tracing_desligado() -> None:
    """Telemetria não derruba atendimento — nem quando está desligada."""
    tracing.marcar_sem_atendimento()


# ─────────────────────── A notificação entra na mesma sessão ───────────────────────


def test_notificacao_e_conversa_caem_na_mesma_sessao(monkeypatch: pytest.MonkeyPatch) -> None:
    """**O conserto do atendimento partido em dois.**

    O disparo era `POST /eventos/link`, sem nome e sem sessão; a conversa era
    `atendimento.TIPO.Nome`, com a sessão da ocorrência. Quem abrisse a sessão
    no Langfuse via a conversa e não via o momento em que a notificação saiu —
    o começo da história ficava de fora.
    """
    monkeypatch.setattr(tracing, "_conteudo", True)
    span = _tracer_falso(monkeypatch)
    monkeypatch.setattr(
        "opentelemetry.trace.get_current_span", lambda *a, **k: span  # noqa: ARG005
    )

    tracing.marcar_notificacao("REMOCAO_BATERIA", QUEM)

    assert span.atributos["langfuse.trace.name"] == "notificacao.REMOCAO_BATERIA.Bruno"
    assert span.atributos["langfuse.session.id"] == QUEM.ocorrencia
    assert span.atributos["evento.tipo"] == "REMOCAO_BATERIA"

    # A conversa usa a MESMA sessão — é o que agrupa os dois no Langfuse.
    with tracing.span_do_turno("REMOCAO_BATERIA", "TEXTO", QUEM):
        pass
    assert span.atributos["langfuse.trace.name"] == "atendimento.REMOCAO_BATERIA.Bruno"
    assert span.atributos["langfuse.session.id"] == QUEM.ocorrencia


def test_notificacao_obedece_a_mesma_trava_de_conteudo(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mesma porta do atendimento. Em produção, ninguém é identificável aqui."""
    monkeypatch.setattr(tracing, "_conteudo", False)
    span = _tracer_falso(monkeypatch)
    monkeypatch.setattr(
        "opentelemetry.trace.get_current_span", lambda *a, **k: span  # noqa: ARG005
    )

    tracing.marcar_notificacao("REMOCAO_BATERIA", QUEM)

    assert span.atributos["langfuse.trace.name"] == "notificacao.REMOCAO_BATERIA"
    for pegada in ("Bruno", "Silva", "999999999", "ABC-1234"):
        assert pegada not in span.tudo_em_texto(), f"'{pegada}' vazou na notificação"
    # A ocorrência continua: identificador interno, não pessoa.
    assert span.atributos["langfuse.session.id"] == QUEM.ocorrencia


def test_marcar_notificacao_e_inerte_com_tracing_desligado() -> None:
    tracing.marcar_notificacao("REMOCAO_BATERIA", QUEM)


# ─────────────────────── Qual turno é qual ───────────────────────


def test_o_rotulo_diz_o_numero_do_turno(monkeypatch: pytest.MonkeyPatch) -> None:
    """Três turnos do mesmo atendimento chegavam com rótulo idêntico.

    A única forma de saber qual era qual era abrir um por um e ler o horário.
    """
    monkeypatch.setattr(tracing, "_conteudo", True)
    span = _tracer_falso(monkeypatch)

    quem = tracing.Identificacao(ocorrencia="OC-1", nome="Bruno da Silva", turno=2)
    with tracing.span_do_turno("REMOCAO_BATERIA", "TEXTO", quem):
        pass

    assert span.atributos["langfuse.trace.name"] == "atendimento.REMOCAO_BATERIA.Bruno.turno-2"
    assert span.atributos["atendimento.turno_numero"] == 2
    # Metadado também: dá para filtrar "todos os turnos 3" e ver onde as
    # conversas costumam se arrastar.
    assert span.atributos["langfuse.trace.metadata.turno"] == 2


def test_o_numero_do_turno_sai_ate_em_producao(monkeypatch: pytest.MonkeyPatch) -> None:
    """"Turno 2" não identifica ninguém — não entra na regra de privacidade.

    Se entrasse, sumiria justamente onde mais faria falta: em produção, onde o
    nome não sai e o rótulo já é o mesmo para todos.
    """
    monkeypatch.setattr(tracing, "_conteudo", False)
    span = _tracer_falso(monkeypatch)

    quem = tracing.Identificacao(ocorrencia="OC-1", nome="Bruno da Silva", turno=3)
    with tracing.span_do_turno("REMOCAO_BATERIA", "TEXTO", quem):
        pass

    assert span.atributos["langfuse.trace.name"] == "atendimento.REMOCAO_BATERIA.turno-3"
    assert "Bruno" not in span.tudo_em_texto()
    assert span.atributos["atendimento.turno_numero"] == 3


def test_notificacao_nao_ganha_numero_de_turno(monkeypatch: pytest.MonkeyPatch) -> None:
    """O disparo não é turno de conversa — e assim ordena antes dos outros."""
    monkeypatch.setattr(tracing, "_conteudo", True)
    span = _tracer_falso(monkeypatch)
    monkeypatch.setattr(
        "opentelemetry.trace.get_current_span", lambda *a, **k: span  # noqa: ARG005
    )

    tracing.marcar_notificacao(
        "REMOCAO_BATERIA", tracing.Identificacao(ocorrencia="OC-1", nome="Bruno")
    )

    assert span.atributos["langfuse.trace.name"] == "notificacao.REMOCAO_BATERIA.Bruno"
    assert "turno" not in span.atributos["langfuse.trace.name"]


def test_o_agente_passa_o_numero_do_turno() -> None:
    """Confere a chamada real: `turnos_ia` conta os que já saíram, este é o próximo."""
    from central_ia.api.rotas import whatsapp

    assert "turno=sessao.turnos_ia + 1" in inspect.getsource(whatsapp._falar)
