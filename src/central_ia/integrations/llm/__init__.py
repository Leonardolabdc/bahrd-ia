"""Implementações da porta :mod:`central_ia.ports.llm`."""

from __future__ import annotations

from central_ia.config import Settings
from central_ia.ports.llm import ClienteLLM


def construir_cliente_llm(cfg: Settings, modelo: str | None = None) -> ClienteLLM:
    """Única linha que decide o provedor. O agente não sabe qual está em uso.

    `modelo` sobrepõe o do `.env` **só para este cliente**, e existe porque a
    Central pode trocar o cérebro quando as respostas ao cliente estiverem
    ruins. Quem passa é a sessão, que carimbou o modelo na abertura: assim a
    troca vale da próxima conversa em diante, e ninguém tem o cérebro trocado no
    meio de um turno.

    ⛔ Vazio cai no `.env`, nunca em string vazia: `""` iria parar no campo
    `model` do payload e voltaria como erro do provedor, não como configuração
    ausente.
    """
    if cfg.llm_provider == "openrouter":
        from central_ia.integrations.llm.openrouter import ClienteOpenRouter

        return ClienteOpenRouter(cfg, modelo=modelo or None)

    from central_ia.integrations.llm.anthropic_cliente import ClienteAnthropic

    return ClienteAnthropic(cfg, modelo=modelo or None)


__all__ = ["construir_cliente_llm"]
