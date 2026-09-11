"""Conexão com o MySQL — camada operacional (conversas, mensagens, métricas).

Local: `mysql:8.4` em container.
OCI:   MySQL HeatWave Database Service, endpoint privado, TLS obrigatório.

O delta é só `MYSQL_SSL_MODE`. TLS já é exercitado em local para que
`REQUIRED` na Fase 2 não seja a primeira vez que o caminho roda.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from central_ia.config import Settings

_engine: AsyncEngine | None = None


def _connect_args(cfg: Settings) -> dict:
    if cfg.mysql_ssl_mode == "DISABLED":
        return {}
    # aiomysql ativa TLS com qualquer dicionário `ssl` não vazio.
    return {"ssl": {"check_hostname": cfg.mysql_ssl_mode == "REQUIRED"}}


def engine(cfg: Settings) -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            cfg.mysql_url,
            pool_size=10,
            max_overflow=5,
            pool_pre_ping=True,       # descarta conexão morta após failover
            pool_recycle=1800,
            connect_args=_connect_args(cfg),
        )
    return _engine


async def fechar_engine() -> None:
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


async def verificar(cfg: Settings) -> None:
    """Sonda de prontidão."""
    async with engine(cfg).connect() as conexao:
        await conexao.execute(text("SELECT 1"))
