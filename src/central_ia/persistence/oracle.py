"""Conexão com o Oracle — sistema de registro.

Local: Oracle Database Free 23ai em container (`oracle:1521/FREEPDB1`).
OCI:   Autonomous Database Serverless 23ai, por wallet/mTLS.

O único delta entre os dois é a presença de `ORACLE_WALLET_DIR`. Nenhum DDL da
aplicação depende de privilégio de DBA — ver `migrations/oracle/`.
"""

from __future__ import annotations

import oracledb

from central_ia.config import Settings

_pool: oracledb.AsyncConnectionPool | None = None


def _parametros_wallet(cfg: Settings) -> dict:
    """Só a Fase 2 usa wallet; em dev o dicionário sai vazio."""
    if not cfg.oracle_wallet_dir:
        return {}
    return {
        "config_dir": cfg.oracle_wallet_dir,
        "wallet_location": cfg.oracle_wallet_dir,
        "wallet_password": (
            cfg.oracle_wallet_password.get_secret_value()
            if cfg.oracle_wallet_password
            else None
        ),
    }


async def abrir_pool(cfg: Settings) -> oracledb.AsyncConnectionPool:
    global _pool
    if _pool is None:
        _pool = oracledb.create_pool_async(
            user=cfg.oracle_user,
            password=cfg.oracle_password.get_secret_value(),
            dsn=cfg.oracle_dsn,
            min=cfg.oracle_pool_min,
            max=cfg.oracle_pool_max,
            increment=1,
            **_parametros_wallet(cfg),
        )
    return _pool


async def fechar_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close(force=False)  # drena conexões em uso; não corta conversa
        _pool = None


async def verificar(cfg: Settings) -> None:
    """Sonda de prontidão. Levanta exceção se o banco não responder."""
    pool = await abrir_pool(cfg)
    async with pool.acquire() as conexao:
        with conexao.cursor() as cursor:
            await cursor.execute("SELECT 1 FROM dual")
            await cursor.fetchone()
