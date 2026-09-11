"""Fonte de rastreamento de amostra — enquanto não há acesso à Bahrd.

Três veículos, um por botão do simulador:

* `XYZ4E56` — tudo aponta para acionamento acidental: em rota, velocidade
  normal, nenhum evento correlato, e o equipamento tem histórico de pânicos
  que o operador **confirmou** como acidentais.
* `RST7U88` — o oposto: fora de rota, parado onde não havia parada prevista,
  e com um evento de jammer na mesma janela.
* `GHI7J89` — remoção de bateria com o veículo parado num ponto de apoio; é o
  caso elegível, em que a IA conduz a conversa.

O segundo existe para provar que a triagem não diz "falso" para tudo. Uma
demonstração que só mostra o caso fácil não demonstra nada.

IMEI desconhecido **não** cai no contexto de outro veículo: recebe uma ficha
neutra com o próprio identificador. Devolver o motorista errado seria pior que
não devolver nada — a IA chamaria a pessoa pelo nome de outra.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from central_ia.ports.rastreamento import (
    ContextoDoVeiculo,
    EventoHistorico,
    FichaVeiculo,
    Posicao,
)


def _historico(
    base: datetime, entradas: list[tuple[int, str, str | None]]
) -> list[EventoHistorico]:
    return [
        EventoHistorico(
            momento=base - timedelta(days=dias), tipo_evento=tipo, desfecho_operador=desfecho
        )
        for dias, tipo, desfecho in entradas
    ]


class FonteAmostra:
    """Implementa :class:`~central_ia.ports.rastreamento.FonteRastreamento`."""

    async def contexto(self, imei: str, momento: datetime) -> ContextoDoVeiculo:
        if imei == "RST7U88":
            return self._suspeito(momento)
        if imei == "GHI7J89":
            return self._bateria(momento)
        if imei == "XYZ4E56":
            return self._provavel_acidental(momento)
        return self._desconhecido(imei, momento)

    # ────────────────────────── caso 1 ──────────────────────────

    def _provavel_acidental(self, momento: datetime) -> ContextoDoVeiculo:
        return ContextoDoVeiculo(
            ficha=FichaVeiculo(
                placa="XYZ4E56",
                imei="XYZ4E56",
                modelo="Scania R450",
                cliente="Transportes Aurora",
                motorista="Marcos Pereira",
                gestor="Regina Alves",
                valor_carga_ref=118700.0,
            ),
            posicao=Posicao(
                momento=momento,
                latitude=-25.5759704,
                longitude=-49.3123914,
                endereco="Rodovia Régis Bittencourt · Curitiba - PR",
                velocidade_kmh=82.0,
                ignicao=True,
                em_rota=True,
                desvio_km=0.0,
            ),
            historico_90d=_historico(
                momento,
                [
                    (7, "Pânico", "acionamento acidental confirmado pelo motorista"),
                    (23, "Velocidade excedida", "justificado_pelo_motorista"),
                    (41, "Pânico", "acionamento acidental confirmado pelo motorista"),
                    (58, "Pânico", "acionamento acidental confirmado pelo gestor"),
                    (66, "Erro na bateria backup", "chamado de manutenção aberto"),
                ],
            ),
            eventos_correlatos=[],
        )

    # ────────────────────────── caso 2 ──────────────────────────

    def _suspeito(self, momento: datetime) -> ContextoDoVeiculo:
        return ContextoDoVeiculo(
            ficha=FichaVeiculo(
                placa="RST7U88",
                imei="RST7U88",
                modelo="Volvo FH 460",
                cliente="Vale Verde Logística",
                motorista="Edson Lima",
                gestor="Iracema Lopes",
                valor_carga_ref=214500.0,
            ),
            posicao=Posicao(
                momento=momento,
                latitude=-23.6443891,
                longitude=-46.5846535,
                endereco="Rodovia Anchieta · acostamento, São Bernardo do Campo - SP",
                velocidade_kmh=0.0,
                ignicao=False,
                em_rota=False,
                desvio_km=11.4,
            ),
            historico_90d=_historico(
                momento,
                [
                    (34, "Velocidade excedida", "orientacao_registrada"),
                    (72, "Entrou na cerca", None),
                ],
            ),
            eventos_correlatos=[
                EventoHistorico(
                    momento=momento - timedelta(minutes=2),
                    tipo_evento="Suspeita de travamento por jammer de GPS",
                ),
                EventoHistorico(
                    momento=momento - timedelta(minutes=6),
                    tipo_evento="Em movimento com ignição desligada",
                ),
            ],
        )

    # ────────────────────────── caso 3 ──────────────────────────

    def _bateria(self, momento: datetime) -> ContextoDoVeiculo:
        """Remoção de bateria com o veículo parado — o caso que a IA conduz."""
        return ContextoDoVeiculo(
            ficha=FichaVeiculo(
                placa="GHI7J89",
                imei="GHI7J89",
                modelo="Scania R 450",
                cliente="Transportes Aurora",
                motorista="Bruno Ramos",
                gestor="Regina Alves",
                valor_carga_ref=118500.0,
            ),
            posicao=Posicao(
                momento=momento,
                latitude=-21.1080033,
                longitude=-47.7834657,
                endereco="Rodovia Anhanguera · posto de apoio, Ribeirão Preto - SP",
                velocidade_kmh=0.0,
                ignicao=False,
                em_rota=True,
                desvio_km=0.0,
            ),
            historico_90d=_historico(
                momento,
                [
                    (12, "Remoção da bateria principal", "chave_geral_desligada_pelo_motorista"),
                    (44, "Velocidade excedida", "velocidade_normalizada_apos_contato"),
                ],
            ),
            eventos_correlatos=[],
        )

    # ─────────────────────── IMEI fora da amostra ───────────────────────

    def _desconhecido(self, imei: str, momento: datetime) -> ContextoDoVeiculo:
        """Ficha neutra, com o identificador que foi pedido.

        Devolver o contexto de outro veículo seria pior que devolver pouco: a
        IA chamaria a pessoa pelo nome de outra e o operador leria uma posição
        que não é a do caminhão dele.
        """
        return ContextoDoVeiculo(
            ficha=FichaVeiculo(placa=imei, imei=imei, cliente=None, motorista=None),
            posicao=None,
            historico_90d=[],
            eventos_correlatos=[],
        )
