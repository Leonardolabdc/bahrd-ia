"""Adaptadores da plataforma de rastreamento da Bahrd."""

from central_ia.config import Settings
from central_ia.integrations.rastreamento.bahrd import (
    EventoRastreamento,
    deduplicar,
    parse_linha_relatorio,
)
from central_ia.ports.rastreamento import FonteRastreamento


def construir_fonte(cfg: Settings) -> FonteRastreamento:
    """Única linha que decide a origem dos dados de rastreamento."""
    if cfg.fonte_rastreamento == "link":
        from central_ia.integrations.rastreamento.bahrd_api import FonteBahrd

        return FonteBahrd(cfg)

    from central_ia.integrations.rastreamento.amostra import FonteAmostra

    return FonteAmostra()


__all__ = [
    "EventoRastreamento",
    "construir_fonte",
    "deduplicar",
    "parse_linha_relatorio",
]
