"""Redis — barramento de eventos (Streams) e cache/locks.

Local: `redis:7-alpine`.
OCI:   OCI Cache (Redis 7), endpoint privado com *auth token*.

O delta é só o endpoint e a credencial, ambos por variável de ambiente.
"""

from __future__ import annotations

from redis.asyncio import Redis

from central_ia.config import Settings

_cliente: Redis | None = None


def cliente(cfg: Settings) -> Redis:
    global _cliente
    if _cliente is None:
        _cliente = Redis.from_url(
            cfg.redis_url,
            decode_responses=True,
            health_check_interval=30,
        )
    return _cliente


async def fechar_cliente() -> None:
    global _cliente
    if _cliente is not None:
        await _cliente.aclose()
        _cliente = None


async def verificar(cfg: Settings) -> None:
    """Sonda de prontidão."""
    await cliente(cfg).ping()
