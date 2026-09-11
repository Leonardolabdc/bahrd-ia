"""Fonte de rastreamento da Bahrd — **aguardando acesso de leitura**.

O contrato já está fechado (:mod:`central_ia.ports.rastreamento`) e o parser do
formato deles já existe e é testado contra o export real
(:mod:`central_ia.integrations.rastreamento.bahrd`). O que falta é só o acesso.

Quando ele chegar, o trabalho aqui é preencher três consultas:

===========================  ==================================================
`ficha`                      cadastro do veículo: cliente, motorista, gestor
`posicao`                    última posição, com velocidade, ignição e rota
`historico` e `correlatos`   eventos por equipamento, com o desfecho que o
                             operador registrou ao encerrar
===========================  ==================================================

O terceiro é o que mais importa e o mais fácil de esquecer no pedido: sem o
**desfecho registrado pelo operador**, a triagem não distingue "equipamento com
histórico de acionamento acidental confirmado" de "equipamento que já disparou
antes". A primeira é evidência; a segunda é coincidência.

Enquanto isso, `FONTE_RASTREAMENTO=amostra` mantém tudo funcionando.
"""

from __future__ import annotations

from datetime import datetime

from central_ia.config import Settings
from central_ia.ports.rastreamento import ContextoDoVeiculo


class FonteBahrd:
    """Implementa :class:`~central_ia.ports.rastreamento.FonteRastreamento`."""

    def __init__(self, cfg: Settings) -> None:
        cfg.exigir("bahrd_api_base_url")
        self._base_url = cfg.bahrd_api_base_url
        self._token = cfg.bahrd_api_token

    async def contexto(self, imei: str, momento: datetime) -> ContextoDoVeiculo:  # pragma: no cover
        raise NotImplementedError(
            "Fonte da Bahrd ainda não implementada — falta o acesso de leitura à "
            "plataforma. Use FONTE_RASTREAMENTO=amostra até lá."
        )
