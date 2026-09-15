"""Conexão com o MySQL — camada operacional (conversas, mensagens, métricas).

Local: `mysql:8.4` em container.
OCI:   MySQL HeatWave Database Service, endpoint privado, TLS obrigatório.

O delta é só `MYSQL_SSL_MODE`.

⚠️ **Este arquivo afirmava que o caminho TLS já era exercitado em local, e não
era.** O `docker-compose.yml` usa `DISABLED`, então `_connect_args` devolvia
`{}` em todo teste e em todo desenvolvimento. A primeira execução real do ramo
`REQUIRED` foi contra o MySQL HeatWave, em 15/09/2026, e ele quebrou na hora:
o dicionário que o código montava não é aceito pelo aiomysql atual, que exige
um `ssl.SSLContext`. `test_mysql_tls.py` existe para a afirmação passar a ser
verdadeira.
"""

from __future__ import annotations

import ssl

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from central_ia.config import Settings

_engine: AsyncEngine | None = None


def _connect_args(cfg: Settings) -> dict:
    """Parâmetros de conexão. Só `ssl`, e só quando TLS está ligado.

    ⛔ **Precisa ser um `SSLContext`, não um dicionário.** O aiomysql antigo
    aceitava qualquer dicionário não vazio como "ligue o TLS"; o atual passa o
    valor direto para o protocolo, que chama `wrap_bio` nele. Com um dicionário
    o erro é `AttributeError: 'dict' object has no attribute 'wrap_bio'` — que
    não menciona TLS, não menciona MySQL, e aparece como dependência
    indisponível na sonda de prontidão.

    **Por que não verifica o certificado.** `REQUIRED`, no MySQL, significa
    "exija criptografia" — não "verifique a identidade do servidor". Verificar
    é `VERIFY_CA` e `VERIFY_IDENTITY`, que são outros modos. E aqui não haveria
    como: o HeatWave é alcançado por endereço privado, e nenhum certificado
    casa com um IP. O que protege a identidade do servidor neste desenho é a
    sub-rede privada, não o certificado.
    """
    if cfg.mysql_ssl_mode == "DISABLED":
        return {}
    contexto = ssl.create_default_context()
    contexto.check_hostname = False
    contexto.verify_mode = ssl.CERT_NONE
    return {"ssl": contexto}


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
