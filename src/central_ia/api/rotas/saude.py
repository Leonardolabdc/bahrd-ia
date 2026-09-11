"""Sondas de saúde.

Dois endpoints com propósitos diferentes — confundi-los derruba o serviço em
produção:

``/saude/vivo``    *liveness*. Responde enquanto o processo está sadio. **Não
                   toca em banco**: se o Oracle cair, matar e recriar o
                   container não resolve nada e só piora a indisponibilidade.

``/saude/pronto``  *readiness*. Verifica Oracle, MySQL e Redis. Retorna 503
                   enquanto alguma dependência estiver fora, e o balanceador
                   para de mandar tráfego — sem reiniciar o processo.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Response, status

from central_ia import __version__
from central_ia.config import settings
from central_ia.observability.logging import logger
from central_ia.persistence import mysql, oracle, redis_bus

router = APIRouter(prefix="/saude", tags=["saude"])
log = logger(__name__)


@router.get("/vivo", summary="Liveness — o processo está de pé?")
async def vivo() -> dict[str, Any]:
    cfg = settings()
    return {
        "status": "vivo",
        "servico": cfg.app_nome,
        "versao": __version__,
        "ambiente": cfg.app_env,
    }


async def _sondar(nome: str, coro) -> tuple[str, dict[str, Any]]:
    try:
        await asyncio.wait_for(coro, timeout=5.0)
        return nome, {"ok": True}
    except Exception as erro:  # noqa: BLE001 — qualquer falha é indisponibilidade
        log.warning("dependencia_indisponivel", dependencia=nome, erro=str(erro))
        return nome, {"ok": False, "erro": type(erro).__name__}


@router.get("/pronto", summary="Readiness — as dependências respondem?")
async def pronto(resposta: Response) -> dict[str, Any]:
    cfg = settings()

    resultados = dict(
        await asyncio.gather(
            _sondar("oracle", oracle.verificar(cfg)),
            _sondar("mysql", mysql.verificar(cfg)),
            _sondar("redis", redis_bus.verificar(cfg)),
        )
    )

    tudo_ok = all(r["ok"] for r in resultados.values())
    if not tudo_ok:
        resposta.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": "pronto" if tudo_ok else "indisponivel",
        "kill_switch_ativo": cfg.kill_switch_ativo,
        "modo_voz": cfg.modo_voz,
        "dependencias": resultados,
    }
