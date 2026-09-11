"""Log em JSON no stdout — nunca em arquivo.

É o que `docker logs` e o OCI Logging esperam (doc 02 §3.4). Escrever em
arquivo dentro do container significa perder o log no primeiro restart e
encher o disco do nó no segundo.
"""

from __future__ import annotations

import logging
import sys

import structlog

from central_ia.config import Settings

# Campos que nunca podem sair em log — LGPD, doc 02 §11.
CAMPOS_SENSIVEIS = frozenset(
    {
        "senha",
        "senha_hash",
        "senha_coacao",
        "senha_coacao_hash",
        "valor_informado",
        "authorization",
        "api_key",
        "token",
        "access_token",
        "telefone",
        "telefone_e164",
        "documento",
    }
)


def _redigir(_logger: object, _metodo: str, evento: dict) -> dict:
    """Substitui valores sensíveis por marcador antes de serializar."""
    for chave in list(evento):
        if chave.lower() in CAMPOS_SENSIVEIS:
            evento[chave] = "[redigido]"
    return evento


def configurar_logging(cfg: Settings) -> None:
    """Idempotente — pode ser chamado no boot da API e de cada worker."""
    nivel = getattr(logging, cfg.log_level.upper(), logging.INFO)

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=nivel,
        force=True,
    )

    processadores: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        _redigir,
    ]

    if cfg.log_formato == "console":
        processadores.append(structlog.dev.ConsoleRenderer())
    else:
        processadores.append(structlog.processors.JSONRenderer())

    structlog.configure(
        processors=processadores,
        wrapper_class=structlog.make_filtering_bound_logger(nivel),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    structlog.contextvars.bind_contextvars(servico=cfg.app_nome, ambiente=cfg.app_env)


def logger(nome: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(nome)
