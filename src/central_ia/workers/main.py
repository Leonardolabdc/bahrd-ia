"""Definição do worker arq.

Executado por ``arq central_ia.workers.main.WorkerSettings``. A mesma imagem
do api-gateway roda aqui — muda o comando, não a imagem.

O arq trata SIGTERM: para de puxar tarefa nova e termina as em andamento
antes de sair.
"""

from __future__ import annotations

from arq.connections import RedisSettings

from central_ia.config import settings
from central_ia.observability.logging import configurar_logging, logger
from central_ia.persistence import mysql, oracle, redis_bus

log = logger(__name__)


async def pulso(ctx: dict) -> None:
    """Tarefa de fumaça — confirma que o worker está processando a fila.

    Some no Sprint 1, quando entram triagem, orquestração e QA.
    """
    log.info("pulso_worker", tentativa=ctx.get("job_try"))


async def ao_iniciar(ctx: dict) -> None:
    cfg = settings()
    configurar_logging(cfg)
    ctx["cfg"] = cfg
    log.info("worker_iniciando", ambiente=cfg.app_env, fila=cfg.redis_stream_eventos)


async def ao_encerrar(_ctx: dict) -> None:
    log.info("worker_encerrando")
    await oracle.fechar_pool()
    await mysql.fechar_engine()
    await redis_bus.fechar_cliente()


def _redis_settings() -> RedisSettings:
    cfg = settings()
    return RedisSettings(
        host=cfg.redis_host,
        port=cfg.redis_port,
        password=(
            cfg.redis_auth_token.get_secret_value() if cfg.redis_auth_token else None
        ),
    )


class WorkerSettings:
    functions = [pulso]
    on_startup = ao_iniciar
    on_shutdown = ao_encerrar
    redis_settings = _redis_settings()

    # Timers e SLA da ocorrência entram aqui no Sprint 2 (cron_jobs).
    max_jobs = 20
    job_timeout = 300
    keep_result = 3600

    # O arq grava um registro de saúde no Redis nesse intervalo, e é o que
    # `arq --check` lê. O padrão é 3600s — inútil como sonda de container,
    # porque um worker travado só apareceria uma hora depois.
    health_check_interval = 30
