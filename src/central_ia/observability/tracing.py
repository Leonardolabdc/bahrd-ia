"""Rastreamento distribuído — OpenTelemetry, exportado para onde a config mandar.

O Jaeger já sobe no `docker compose` escutando OTLP em 4317. Este módulo liga a
aplicação nele — e, quando há credencial, manda **os mesmos spans** também para
o Langfuse. Dois destinos, um provedor, nenhuma duplicação de instrumentação.

Uma correção ao que este cabeçalho dizia antes: trocar de backend **não** é só
mexer em `OTEL_EXPORTER_OTLP_ENDPOINT`. O Jaeger e o APM da OCI recebem OTLP por
gRPC; o Langfuse aceita **só HTTP**. Por isso os dois exportadores coexistem
aqui, de classes diferentes, e por isso ligar o Langfuse foi código, não config.

**A regra que governa este módulo: span carrega metadado, nunca conteúdo.**

Latência, tokens, custo e desfecho vão para o trace. Prompt, resposta, nome de
motorista, placa e endereço **não**. Dois motivos, e os dois pesam:

* A conversa **já é registrada** na trilha de auditoria da ocorrência, num
  formato moldado ao domínio e sob controle da Bahrd. Duplicar num trace é pagar
  duas vezes — em disco e em exposição — pela mesma informação.
* Telemetria não parece fluxo de dado pessoal, e é o mais completo de todos.
  Um backend de observabilidade recebe *toda* conversa com *todo* motorista.

**A exceção, e o desenho dela.** Depurar prompt sem ver o prompt é adivinhação,
e é para isso que o Langfuse existe. Então há um caminho para o conteúdo sair —
`langfuse_com_conteudo` —, com duas travas em série: uma variável que nasce
desligada, e um bloqueio em produção que nenhuma variável destrava. A conta é
que em desenvolvimento o dado é fictício e o ganho é real; em produção o dado é
de um motorista de verdade e o ganho não paga.

Fora essa porta, `span_do_turno` continua recebendo parâmetros nomeados e
tipados em vez de um dicionário aberto: não existe outro lugar onde encaixar um
prompt sem alterar a assinatura, e alterar assinatura passa por revisão.

Nada aqui pode derrubar um atendimento. Sem endpoint configurado, o módulo é
inerte; se a inicialização falhar, ela registra e segue. Observabilidade que
tira o sistema do ar é pior que observabilidade nenhuma.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from central_ia.observability.logging import logger

if TYPE_CHECKING:
    from fastapi import FastAPI

    from central_ia.config import Settings
    from central_ia.ports.llm import Mensagem

log = logger(__name__)

#: Ligado por `configurar_tracing`. Enquanto for `None`, os spans são no-op.
_tracer: Any | None = None

#: Espelha `cfg.langfuse_com_conteudo` no momento da configuração. Fica em
#: módulo porque `Turno.registrar` não recebe `Settings` — e porque assim o
#: valor é decidido **uma vez**, na subida, e não a cada turno. Só
#: `configurar_tracing` escreve aqui; enquanto for `False`, não existe caminho
#: no código por onde prompt ou resposta cheguem a um span.
_conteudo: bool = False


def configurar_tracing(cfg: Settings, app: FastAPI | None = None) -> bool:
    """Liga a exportação de traces. Devolve `True` se ficou ativa.

    Sem `OTEL_EXPORTER_OTLP_ENDPOINT` **e** sem credencial do Langfuse, não liga
    nada — é o que mantém a suíte de testes e a máquina de quem não subiu o
    Jaeger funcionando sem erro. Com qualquer um dos dois, liga o que dá.
    """
    global _tracer, _conteudo

    endpoint = (cfg.otel_exporter_otlp_endpoint or "").strip()
    if not endpoint and not cfg.langfuse_ativo:
        log.info(
            "tracing_desligado",
            motivo="sem OTEL_EXPORTER_OTLP_ENDPOINT e sem LANGFUSE_PUBLIC_KEY/SECRET_KEY",
        )
        return False

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider

        from central_ia import __version__

        provedor = TracerProvider(
            resource=Resource.create(
                {
                    "service.name": "central-ia",
                    "service.version": __version__,
                    "deployment.environment": cfg.app_env,
                }
            )
        )

        if endpoint:
            _ligar_otlp_grpc(provedor, endpoint)
        if cfg.langfuse_ativo:
            _ligar_langfuse(provedor, cfg)

        trace.set_tracer_provider(provedor)
        _tracer = trace.get_tracer("central_ia")
        _conteudo = cfg.langfuse_com_conteudo

        _instrumentar(app)
        log.info(
            "tracing_ligado",
            endpoint=endpoint or None,
            langfuse=cfg.langfuse_ativo,
            # Vai para o log de propósito: quem abrir o log da subida precisa
            # conseguir responder "esta instância está mandando conversa para
            # fora?" sem ler código nem adivinhar o `.env`.
            langfuse_conteudo=_conteudo,
        )
        return True
    except Exception as erro:  # noqa: BLE001 — telemetria não derruba a API
        log.warning("tracing_falhou", erro=str(erro))
        _tracer = None
        _conteudo = False
        return False


def _ligar_otlp_grpc(provedor: Any, endpoint: str) -> None:
    """Destino padrão: Jaeger no compose, APM da OCI na Fase 2. Ambos gRPC.

    `BatchSpanProcessor` e não `SimpleSpanProcessor`: a exportação sai do
    caminho da requisição. Com o simples, cada span vira uma ida ao coletor
    **dentro** do atendimento — e um coletor lento viraria latência para quem
    está na estrada.
    """
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provedor.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))


#: Trecho de nome de span que denuncia infraestrutura, não atendimento.
#:
#: Medido em 25/08/2026, na primeira hora com o Langfuse ligado. Os dois juntos
#: enterram o plano grátis, que são 50 mil traces por mês:
#:
#: * `/saude` — healthcheck do Docker a cada 15 s: ~172 mil por mês. Oito dias.
#: * `/painel` — o painel faz *polling* de quatro rotas a cada 3 s em tempo real
#:   (`web/src/App.tsx`). São 80 por minuto: **a cota inteira em dez horas** com
#:   uma aba aberta. Fora de tempo real, a cada 15 s, ainda dá 690 mil por mês.
#:
#: E a cota é o menor dos problemas: antes de acabar, a lista de traces já virou
#: uma parede de polling com os atendimentos perdidos no meio — que é o oposto
#: do motivo de existir a ferramenta.
#:
#: E há um terceiro, que não é rota nenhuma. A instrumentação do FastAPI cria um
#: span por mensagem do protocolo ASGI: `POST /rota http receive` e dois
#: `http send`. Medido nos traces reais em 25/08/2026, são **65% a 75% de todos
#: os spans** — três unidades cobradas para transportar a informação de uma.
#: No Jaeger dão o detalhe de onde o tempo foi dentro do ASGI; no Langfuse, que
#: responde "o que o modelo respondeu e quanto custou", não dizem nada.
#:
#: `/whatsapp` e `/eventos` **não** entram aqui: são as portas de entrada de um
#: atendimento de verdade, e o span do turno pendura embaixo delas.
#:
#: O Jaeger continua recebendo tudo: lá é local, ilimitado, e saber que o
#: healthcheck respondeu é exatamente o trabalho dele. O filtro vale só para o
#: destino que cobra e que existe para responder outra pergunta.
_RUIDO_DE_INFRA = ("/saude", "/painel", "http send", "http receive")


def _e_ruido_de_infra(nome: str) -> bool:
    """Este span é infraestrutura? Nome de span do FastAPI é `GET /rota`."""
    return any(marca in nome for marca in _RUIDO_DE_INFRA)


#: Marca posta pela própria rota quando a requisição não carregou atendimento.
#:
#: Existe porque nome de rota não basta. `POST /whatsapp/meta` recebe duas
#: coisas muito diferentes no mesmo endereço: a mensagem do motorista e os
#: avisos de entrega da Meta (enviado, entregue, lido). Um disparo produz três
#: ou quatro avisos, e cada um virava um trace no Langfuse — medido em
#: 25/08/2026: **57 dos últimos 100 traces**, todos com uma observação só e
#: nenhuma conversa dentro.
#:
#: Filtrar a rota pelo nome não serve: o span dela é a **raiz** do atendimento
#: de verdade, com o turno da IA pendurado embaixo. Derrubá-la decapitaria
#: justamente os traces que interessam. Quem sabe distinguir é o código que leu
#: o corpo da requisição — por isso a marca vem de lá, e não daqui.
_SEM_ATENDIMENTO = "atendimento.relevante"


def marcar_sem_atendimento() -> None:
    """Diz que esta requisição não carregou conversa. Inerte sem tracing.

    Só afeta o destino de LLM. O Jaeger continua recebendo o span inteiro:
    saber que a Meta confirmou a entrega é exatamente o trabalho dele.
    """
    if _tracer is None:
        return
    from opentelemetry import trace

    trace.get_current_span().set_attribute(_SEM_ATENDIMENTO, False)


def _ligar_langfuse(provedor: Any, cfg: Settings) -> None:
    """Segundo processador no mesmo provedor — o Jaeger não perde nada.

    Cada processador registrado vê **todo** span e decide o que exporta. É por
    isso que dá para ter os dois destinos sem instrumentar duas vezes.

    Exportador **HTTP**, não gRPC: o Langfuse não fala gRPC. A autenticação é
    Basic com o par de chaves, e o header de versão de ingestão é obrigatório —
    sem ele o evento é aceito e interpretado pelo formato antigo, que está
    marcado para desligar.
    """
    from base64 import b64encode

    from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
        OTLPSpanExporter as OTLPSpanExporterHTTP,
    )
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    class ProcessadorFiltrado(BatchSpanProcessor):
        """Em lote como o outro, mas descarta ruído antes de virar cota.

        O descarte é aqui e não na instrumentação de propósito: tirar a rota da
        instrumentação apagaria o healthcheck do Jaeger também, e lá ele é
        justamente o que se quer ver.
        """

        def on_end(self, span: Any) -> None:
            if _e_ruido_de_infra(span.name):
                return
            # Requisição que a rota marcou como "não trouxe conversa". Seguro
            # descartar a raiz aqui porque, nesses casos, não há filho nenhum
            # pendurado nela — aviso de entrega não chama modelo e não sai
            # para lugar nenhum.
            if (span.attributes or {}).get(_SEM_ATENDIMENTO) is False:
                return
            super().on_end(span)

    segredo = cfg.langfuse_secret_key.get_secret_value() if cfg.langfuse_secret_key else ""
    credencial = b64encode(f"{cfg.langfuse_public_key}:{segredo}".encode()).decode()

    provedor.add_span_processor(
        ProcessadorFiltrado(
            OTLPSpanExporterHTTP(
                endpoint=f"{cfg.langfuse_host.rstrip('/')}/api/public/otel/v1/traces",
                headers={
                    "Authorization": f"Basic {credencial}",
                    "x-langfuse-ingestion-version": "4",
                },
            )
        )
    )


def _instrumentar(app: FastAPI | None) -> None:
    """Instrumentação automática — é o que dá mais retorno por menos esforço.

    O FastAPI traz uma span por rota; o httpx, uma por chamada externa. Com as
    duas, cada ida ao OpenRouter, Twilio, Deepgram e ElevenLabs aparece com
    duração e status sem uma linha de span escrita à mão.
    """
    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

        HTTPXClientInstrumentor().instrument()
    except Exception as erro:  # noqa: BLE001
        log.warning("tracing_httpx_falhou", erro=str(erro))

    if app is None:
        return

    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
    except Exception as erro:  # noqa: BLE001
        log.warning("tracing_fastapi_falhou", erro=str(erro))


@dataclass(frozen=True)
class Identificacao:
    """Por quem procurar um atendimento — e o que disso pode sair daqui.

    Existe como objeto, e não como três parâmetros soltos, porque é aqui que a
    decisão de privacidade fica **visível num lugar só**. `ocorrencia` é
    identificador interno e sai sempre; `telefone`, `nome` e `placa` são dado
    pessoal e saem apenas pela mesma porta do conteúdo da conversa.

    A conta que justifica isso: com a porta aberta, o texto do atendimento já
    vai — e o nome do motorista está *dentro* dele, escrito por ele mesmo.
    Mandar os campos separados não expõe nada novo; só torna **procurável** o
    que já estava lá. Com a porta fechada, nada disso existe no trace.
    """

    ocorrencia: str | None = None
    telefone: str | None = None
    nome: str | None = None
    placa: str | None = None

    #: Qual rodada da conversa é esta, contando a partir de 1.
    #:
    #: Fica **fora** da regra de privacidade de propósito: "turno 2" não
    #: identifica ninguém, e some da tela justamente onde mais faria falta se
    #: fosse tratado como dado pessoal.
    #:
    #: Existe porque três turnos do mesmo atendimento chegavam ao Langfuse com
    #: rótulos idênticos, e a única forma de saber qual era qual era abrir um
    #: por um e ler o horário.
    turno: int | None = None

    #: `link` (evento real) ou `teste` (disparado pela tela da Central).
    #:
    #: ⛔ **Sem isto o Langfuse soma teste com atendimento real**, e a conta de
    #: custo da POC vira ficção. Pior: quem for avaliar por que a IA respondeu
    #: mal não consegue separar o que foi ensaio do que foi cliente de verdade.
    #:
    #: Fica **fora** da regra de privacidade, pelo mesmo motivo que `turno`:
    #: "veio da tela de teste" não identifica ninguém, e é justamente onde a
    #: porta de conteúdo fechada faria mais falta. Em produção, onde a porta
    #: nunca abre, esta é uma das poucas coisas que ainda dá para filtrar.
    origem: str | None = None


@contextmanager
def span_do_turno(
    tipo_evento: str,
    canal: str,
    quem: Identificacao | None = None,
) -> Iterator[Turno]:
    """Envolve uma rodada de conversa. Devolve um objeto para anotar o resultado.

    Os atributos são nomeados de propósito — ver o cabeçalho do módulo. A
    assinatura mudou em 25/08/2026 para abrir a porta de conteúdo descrita lá;
    foi a revisão que o cabeçalho pedia.

    O id da ocorrência vira o id de sessão no Langfuse: é o que faz os turnos
    aparecerem como **uma conversa** em vez de N traces soltos, que é a
    diferença entre ler um atendimento e garimpar spans.
    """
    if _tracer is None:
        yield Turno(None)
        return

    quem = quem or Identificacao()

    with _tracer.start_as_current_span("atendimento.turno") as span:
        span.set_attribute("evento.tipo", tipo_evento)
        span.set_attribute("evento.canal", canal)
        # O Langfuse lê estes dois para montar a tela: o tipo de observação faz
        # o span virar "generation" (com custo e tokens no lugar certo), e o
        # nome do trace é o que aparece na lista.
        span.set_attribute("langfuse.observation.type", "generation")
        span.set_attribute("langfuse.trace.name", _nome_do_trace("atendimento", tipo_evento, quem))

        if quem.ocorrencia:
            span.set_attribute("langfuse.session.id", quem.ocorrencia)
            span.set_attribute("atendimento.ocorrencia", quem.ocorrencia)
        if quem.turno:
            # Fora de `_identificar` porque não é dado pessoal: sai sempre, e
            # como metadado dá para filtrar "todos os turnos 3" e ver onde as
            # conversas costumam se arrastar.
            span.set_attribute("atendimento.turno_numero", quem.turno)
            span.set_attribute("langfuse.trace.metadata.turno", quem.turno)
        if quem.origem:
            # Idem: não é dado pessoal, sai em qualquer ambiente. Como metadado
            # de trace, é o que deixa filtrar `origem = teste` no Langfuse e
            # tirar os ensaios da conta de custo real.
            span.set_attribute("atendimento.origem", quem.origem)
            span.set_attribute("langfuse.trace.metadata.origem", quem.origem)

        _identificar(span, quem)
        yield Turno(span)


@contextmanager
def span_da_triagem(tipo_evento: str, quem: Identificacao | None = None) -> Iterator[Turno]:
    """Envolve a triagem prévia, que decide se um pânico é falso antes do contato.

    ⚠️ **Não existia até 03/09/2026, e era a maior cegueira do tracing.** A
    triagem é a chamada de LLM **mais cara** do fluxo, porque roda com
    `ANTHROPIC_EFFORT_TRIAGEM=high` sobre o resumo inteiro do veículo. Ela
    acontecia fora de qualquer span: no Langfuse, um pânico aparecia com o custo
    da conversa e sem o custo da decisão que autorizou a conversa.

    Pior para o que a Central quer fazer com isto: quando a triagem falha, o caso
    vai para a fila humana sem a IA falar nada. Quem fosse investigar "por que
    esse pânico não teve atendimento" não achava a chamada que falhou, só uma
    linha de log num container.

    Mesma `session.id` do atendimento, então a triagem aparece **antes** dos
    turnos na mesma conversa do Langfuse, que é a ordem em que aconteceu.
    """
    if _tracer is None:
        yield Turno(None)
        return

    quem = quem or Identificacao()

    with _tracer.start_as_current_span("atendimento.triagem") as span:
        span.set_attribute("evento.tipo", tipo_evento)
        span.set_attribute("langfuse.observation.type", "generation")
        span.set_attribute("langfuse.trace.name", _nome_do_trace("triagem", tipo_evento, quem))

        if quem.ocorrencia:
            span.set_attribute("langfuse.session.id", quem.ocorrencia)
            span.set_attribute("atendimento.ocorrencia", quem.ocorrencia)
        if quem.origem:
            span.set_attribute("atendimento.origem", quem.origem)
            span.set_attribute("langfuse.trace.metadata.origem", quem.origem)

        _identificar(span, quem)
        yield Turno(span)


def _nome_do_trace(prefixo: str, tipo_evento: str, quem: Identificacao) -> str:
    """O rótulo que aparece na lista do Langfuse. `atendimento.BATERIA.Antônio`.

    Com dezenas de atendimentos do mesmo tipo na tela, `atendimento.BATERIA`
    repetido vinte vezes não ajuda a achar nenhum. O primeiro nome resolve isso
    sem clicar em nada — e é assim que quem trabalha na central se refere ao
    caso: "o do Antônio", não "a ocorrência OC-2026-08-25-3F2A-WA".

    Só o **primeiro** nome, e só com a porta de conteúdo aberta: nome completo
    identifica melhor e por isso mesmo não vai. Sem a porta, o rótulo volta a
    ser só o tipo do evento, que é o que ele sempre foi.
    """
    # ⚠️ O prefixo de teste vem **antes** de tudo, e é de propósito: a lista do
    # Langfuse ordena por nome, então `teste.` agrupa os ensaios num bloco só
    # em vez de espalhá-los entre os atendimentos reais. Quem for avaliar
    # qualidade lê os de verdade sem tropeçar nos nossos.
    base = f"{prefixo}.{tipo_evento}"
    if quem.origem and quem.origem != "link":
        base = f"{quem.origem}.{base}"

    if _conteudo and quem.nome:
        primeiro = quem.nome.split(",")[0].strip().split(" ")[0]
        if primeiro:
            base = f"{base}.{primeiro}"

    # O número do turno vai em qualquer ambiente: não identifica ninguém, e é
    # o que separa três rodadas do mesmo atendimento numa lista onde, sem ele,
    # as três aparecem com rótulo idêntico.
    return f"{base}.turno-{quem.turno}" if quem.turno else base


def marcar_notificacao(tipo_evento: str, quem: Identificacao) -> None:
    """Batiza o span da rota de eventos com a ocorrência que ele acabou de abrir.

    **Por que existe.** Um atendimento nascia partido em dois traces que não se
    conheciam: `POST /eventos/link`, sem nome e sem sessão, e
    `atendimento.TIPO.Nome`, com a sessão da ocorrência. Quem abrisse a sessão
    no Langfuse via a conversa e **não** via o momento em que a notificação
    saiu — que é justamente o começo da história.

    Com a mesma `session.id` nos dois, a ocorrência inteira lê em ordem: a
    notificação entregue, a resposta do cliente, o turno da IA, o desfecho.

    Só o nome muda de prefixo; o resto é a mesma regra de privacidade do
    atendimento, pela mesma porta. Sem a porta aberta, sai
    `notificacao.REMOCAO_BATERIA` e mais nada de pessoa.
    """
    if _tracer is None:
        return
    from opentelemetry import trace

    span = trace.get_current_span()
    span.set_attribute("langfuse.trace.name", _nome_do_trace("notificacao", tipo_evento, quem))
    span.set_attribute("evento.tipo", tipo_evento)
    if quem.ocorrencia:
        span.set_attribute("langfuse.session.id", quem.ocorrencia)
        span.set_attribute("atendimento.ocorrencia", quem.ocorrencia)
    _identificar(span, quem)


def _identificar(span: Any, quem: Identificacao) -> None:
    """Os campos de busca que são dado pessoal. Mesma porta do conteúdo.

    `langfuse.user.id` recebe o telefone porque é ele que o Langfuse usa para
    agrupar tudo de uma mesma pessoa e para a busca por usuário — é a diferença
    entre achar um atendimento pelo número que o cliente ligou reclamando e ter
    de descobrir antes o id da ocorrência.

    Nome e placa vão como metadado de trace, que é o que o Langfuse deixa
    filtrar. Placa está aqui, e não junto da ocorrência, de propósito: ela
    identifica o veículo de um cliente da Bahrd, e o `.gitignore` deste
    repositório trata placa como dado de cliente desde o primeiro commit.
    """
    if not _conteudo:
        return
    campos = {
        "langfuse.user.id": quem.telefone,
        "langfuse.trace.metadata.nome": quem.nome,
        "langfuse.trace.metadata.placa": quem.placa,
        "langfuse.trace.metadata.telefone": quem.telefone,
    }
    for chave, valor in campos.items():
        if valor:
            span.set_attribute(chave, valor)


class Turno:
    """Anotador do span. Com `_tracer` desligado, todo método é no-op."""

    def __init__(self, span: Any | None) -> None:
        self._span = span

    def registrar(
        self,
        *,
        modelo: str | None = None,
        tokens_entrada: int | None = None,
        tokens_saida: int | None = None,
        tokens_cache: int | None = None,
        custo_usd: float | None = None,
        desfecho_proposto: str | None = None,
        quer_escalar: bool | None = None,
        quer_aguardar: bool | None = None,
        versao_prompt: str | None = None,
        entrada: Sequence[Mensagem] | None = None,
        saida: str | None = None,
    ) -> None:
        """Metadado sempre; `entrada` e `saida` só se a porta estiver aberta.

        Os dois últimos parâmetros são a conversa. Passá-los aqui **não** os
        envia: quem decide é `_conteudo`, e com ele desligado eles são
        ignorados sem deixar rastro. O chamador não precisa saber em que
        ambiente está, e não existe caminho em que ele vaze por engano.
        """
        if self._span is None:
            return
        atributos = {
            "llm.modelo": modelo,
            "llm.tokens_entrada": tokens_entrada,
            "llm.tokens_saida": tokens_saida,
            "llm.tokens_cache": tokens_cache,
            "llm.custo_usd": custo_usd,
            "atendimento.desfecho_proposto": desfecho_proposto,
            "atendimento.quer_escalar": quer_escalar,
            "atendimento.quer_aguardar": quer_aguardar,
            "prompt.versao": versao_prompt,
            # Os mesmos números com os nomes que o Langfuse entende. Sem isto o
            # trace chega, mas sem custo e sem tokens na coluna — que é metade
            # do motivo de ter Langfuse. Os `llm.*` acima ficam: painel de
            # Jaeger montado sobre eles não pode quebrar por causa disto.
            "gen_ai.request.model": modelo,
            "langfuse.observation.model.name": modelo,
            "langfuse.observation.usage_details": _uso_em_json(
                tokens_entrada, tokens_saida, tokens_cache
            ),
            "langfuse.observation.cost_details": (
                json.dumps({"total": custo_usd}) if custo_usd is not None else None
            ),
            "langfuse.observation.metadata.desfecho": desfecho_proposto,
            "langfuse.observation.metadata.versao_prompt": versao_prompt,
        }
        for chave, valor in atributos.items():
            if valor is not None:
                self._span.set_attribute(chave, valor)

        self._registrar_conteudo(entrada, saida)

    def _registrar_conteudo(
        self,
        entrada: Sequence[Mensagem] | None,
        saida: str | None,
    ) -> None:
        """A única porta por onde conversa vira span. Fechada por padrão.

        Sai a resposta **bruta**, antes da limpeza das marcas de controle: é
        justamente o `[ESCALAR]` que o modelo cuspiu no lugar errado que se quer
        ver ao depurar. O texto entregue à pessoa está na trilha de auditoria.
        """
        if self._span is None or not _conteudo:
            return
        if entrada is not None:
            self._span.set_attribute(
                "langfuse.observation.input",
                json.dumps(
                    [{"role": m.papel, "content": m.conteudo} for m in entrada],
                    ensure_ascii=False,
                ),
            )
        if saida is not None:
            self._span.set_attribute("langfuse.observation.output", saida)


def _uso_em_json(entrada: int | None, saida: int | None, cache: int | None) -> str | None:
    """Formato de uso do Langfuse. `None` quando não há número nenhum.

    Chave própria para cache porque a convenção `gen_ai.usage.*` não tem uma — e
    numa POC em que o cache é o que segura o custo, esconder esse número seria
    esconder o principal.
    """
    uso = {"input": entrada, "output": saida, "cache_read_input_tokens": cache}
    presentes = {chave: valor for chave, valor in uso.items() if valor is not None}
    return json.dumps(presentes) if presentes else None
