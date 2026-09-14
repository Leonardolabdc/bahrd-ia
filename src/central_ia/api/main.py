"""Ponto de entrada do api-gateway.

Recebe webhooks (rastreamento, WhatsApp), valida assinatura, deduplica e
publica no barramento; expõe a API do painel. **Nenhuma regra de negócio
mora aqui** — elegibilidade é do motor de políticas, conversa é do agent-core.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from central_ia import __version__
from central_ia.api.rotas import (
    eventos,
    eventos_de_teste,
    midia,
    painel,
    saude,
    whatsapp,
)
from central_ia.api.seguranca import avisar_se_aberto
from central_ia.config import settings
from central_ia.observability.logging import configurar_logging, logger
from central_ia.observability.tracing import configurar_tracing
from central_ia.orchestration.sessao_whatsapp import SESSOES
from central_ia.persistence import mysql, oracle, redis_bus, sessoes_redis

log = logger(__name__)


@asynccontextmanager
async def ciclo_de_vida(_app: FastAPI):
    cfg = settings()
    configurar_logging(cfg)
    avisar_se_aberto()
    log.info(
        "api_iniciando",
        versao=__version__,
        ambiente=cfg.app_env,
        modo_voz=cfg.modo_voz,
        secret_provider=cfg.secret_provider,
        kill_switch_ativo=cfg.kill_switch_ativo,
    )

    # Os pools sobem preguiçosamente: o container fica saudável mesmo se o
    # Oracle ainda estiver iniciando (ele leva minutos no primeiro boot).
    # Quem reporta indisponibilidade é /saude/pronto, não o processo morrendo.

    # As conversas que estavam em andamento quando o processo anterior morreu.
    # Sem isto, todo deploy trata quem estava conversando como desconhecido: a
    # próxima mensagem do motorista chega a um sistema que não sabe quem ele é,
    # e ele responde "sim" a uma pergunta que, deste lado, nunca foi feita.
    # ADR-003.
    voltaram = await sessoes_redis.carregar(cfg, SESSOES)
    if voltaram:
        log.info("conversas_retomadas", quantas=voltaram)

    # As esperas são `asyncio.Task` e não sobrevivem ao processo. Não dá para
    # restaurá-las — só para recomeçá-las, a partir de quem ficou `aguardando`.
    # Uma espera reconstruída recomeça a contar, e isso é diferente da original.
    rearmadas = await whatsapp.rearmar_esperas(SESSOES)
    if rearmadas:
        log.info("esperas_rearmadas", quantas=rearmadas)

    yield

    # Graceful shutdown: drena antes de sair. Sem isso o Kubernetes corta
    # conversa no meio durante um rolling update (doc 02 §3.4).
    log.info("api_encerrando")

    # ⚠️ ANTES de fechar o cliente do Redis, e antes dos outros pools. Num
    # desligamento gracioso — que é o caso do deploy — é isto que torna a
    # janela de perda igual a zero.
    gravadas = await sessoes_redis.sincronizar(cfg, SESSOES)
    log.info("conversas_gravadas_na_saida", quantas=gravadas)

    await oracle.fechar_pool()
    await mysql.fechar_engine()
    await redis_bus.fechar_cliente()


class JSONUtf8(JSONResponse):
    """`application/json; charset=utf-8`, declarado em vez de subentendido.

    JSON é UTF-8 por especificação e todo navegador moderno decodifica assim
    mesmo sem o parâmetro. Mas "por especificação" só protege quem lê a
    especificação: proxy corporativo, WebView antigo e ferramenta de teste que
    adivinham a codificação pelo cabeçalho transformam "ignição" em "igniçăo".

    O conteúdo desta API é quase todo português com acento e nomes de pessoa.
    Declarar custa um cabeçalho.
    """

    media_type = "application/json; charset=utf-8"


def criar_app() -> FastAPI:
    cfg = settings()
    app = FastAPI(
        title="POC IA — Central de Monitoramento Bahrd",
        version=__version__,
        lifespan=ciclo_de_vida,
        default_response_class=JSONUtf8,
        # Documentação interativa só fora de produção
        docs_url="/docs" if not cfg.em_producao else None,
        redoc_url=None,
        openapi_url="/openapi.json" if not cfg.em_producao else None,
    )

    # O painel é servido de outra origem (Vite em :5173 no dev, nginx atrás do
    # OCI Load Balancer em produção), então precisa de CORS explícito.
    # A lista vem do ambiente: em produção é o domínio do painel, nunca "*".
    if cfg.origens_cors:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cfg.origens_cors,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PATCH", "DELETE"],
            allow_headers=["*"],
        )

    app.include_router(saude.router)
    app.include_router(painel.router)
    app.include_router(whatsapp.router)
    app.include_router(eventos.router)
    app.include_router(midia.router)
    # Registrada sempre; quem decide se existe é `testes_pelo_painel`, dentro
    # dela, devolvendo 404. Condicionar o `include_router` aqui pareceria mais
    # seguro e seria pior: a rota sumiria do `/openapi.json` conforme o
    # ambiente, e ninguém descobriria por que o botão da tela não funciona.
    app.include_router(eventos_de_teste.router)

    # ── Espelho das conversas no Redis ──────────────────────────────────────
    #
    # Grava na saída de cada requisição, e não a cada mutação. O motivo está em
    # `persistence/sessoes_redis.py`: quase toda mutação acontece no objeto
    # `Sessao`, não nos métodos de `Sessoes`, então não há ponto único para
    # interceptar. Comparar o payload inteiro no fim da requisição pega tudo —
    # não importa quem mudou o quê, nem onde.
    #
    # Fica **depois** do roteador e do tracing de propósito: middleware do
    # Starlette executa na ordem inversa do registro, e este precisa rodar por
    # último na volta, quando a rota já terminou de mexer na sessão.
    @app.middleware("http")
    async def espelhar_sessoes(requisicao, proxima):  # type: ignore[no-untyped-def]
        resposta = await proxima(requisicao)
        # Nunca levanta: ver a docstring de `sincronizar`. Uma falha aqui não
        # pode transformar uma resposta 200 em erro para quem está conversando.
        await sessoes_redis.sincronizar(cfg, SESSOES)
        return resposta

    # Instrumentação vai **aqui**, na construção — não no `lifespan`.
    #
    # `instrument_app` acrescenta middleware, e o Starlette congela a pilha de
    # middleware quando o servidor sobe. Chamado no ciclo de vida, o registro
    # acontece tarde demais: nenhuma rota é traçada, sem erro nenhum para
    # denunciar. Descobrimos pelo sintoma — o Jaeger recebia span manual e
    # nenhum de requisição.
    #
    # Sem endpoint configurado é inerte, e falha aqui não impede a API de
    # subir: telemetria que derruba atendimento é pior que telemetria nenhuma.
    configurar_tracing(cfg, app)

    # Sprint 1: /webhooks/rastreamento, /webhooks/whatsapp
    # Sprint 2: /painel/ocorrencias/{id}/assumir, /painel/kill-switch

    return app


app = criar_app()
