"""Porta da fonte de dados do rastreamento.

É daqui que sai tudo o que a IA cruza para decidir: ficha do veículo, posição
atual, histórico do equipamento e eventos correlatos na janela.

Duas implementações:

* **amostra** — dados fixos, para construir e demonstrar sem depender de
  ninguém. É o que roda hoje.
* **link** — a plataforma da Bahrd, quando houver acesso de leitura. O contrato
  abaixo foi desenhado a partir do que o Relatório de Eventos já entrega
  (`docs/exemplos/Relatorio de Eventos.xls`), então a tradução é direta.

O que o consumidor vê é este contrato. Trocar a origem é uma linha na
composição — nem a triagem nem o painel sabem de onde os dados vieram.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, Field


class FichaVeiculo(BaseModel):
    placa: str
    imei: str
    modelo: str | None = None
    cliente: str | None = None
    motorista: str | None = None
    gestor: str | None = None
    valor_carga_ref: float | None = None


class Posicao(BaseModel):
    momento: datetime
    latitude: float | None = None
    longitude: float | None = None
    endereco: str | None = None
    velocidade_kmh: float | None = None
    ignicao: bool | None = None
    em_rota: bool | None = Field(
        default=None, description="A posição bate com a rota prevista da viagem?"
    )
    desvio_km: float | None = None


class EventoHistorico(BaseModel):
    momento: datetime
    tipo_evento: str
    desfecho_operador: str | None = Field(
        default=None,
        description="O que o operador registrou ao encerrar. É o que permite "
        "distinguir acionamento acidental confirmado de suposição.",
    )


class ContextoDoVeiculo(BaseModel):
    """Tudo o que a triagem precisa, num objeto só."""

    ficha: FichaVeiculo
    posicao: Posicao | None = None
    historico_90d: list[EventoHistorico] = []
    eventos_correlatos: list[EventoHistorico] = Field(
        default=[],
        description="Outros eventos do mesmo veículo na janela do alerta — "
        "jammer, isca, movimento anômalo. É o sinal que mais pesa contra "
        "classificar um pânico como falso.",
    )

    def resumo_para_triagem(self) -> dict[str, object]:
        """Achata o contexto no formato que o prompt de triagem lê.

        Fica aqui, e não no prompt, para que trocar a fonte de dados não exija
        reescrever a instrução do modelo.
        """
        acidentais = [
            e
            for e in self.historico_90d
            if e.desfecho_operador and "acident" in e.desfecho_operador.lower()
        ]
        panicos = [e for e in self.historico_90d if "pânico" in e.tipo_evento.lower()]

        return {
            "veículo": f"{self.ficha.placa} · {self.ficha.modelo or '?'}",
            "cliente": self.ficha.cliente or "não informado",
            "motorista": self.ficha.motorista or "não informado",
            "posição": self.posicao.endereco if self.posicao else "sem posição recente",
            "velocidade": (
                f"{self.posicao.velocidade_kmh} km/h" if self.posicao else "desconhecida"
            ),
            "ignição": (
                ("ligada" if self.posicao.ignicao else "desligada")
                if self.posicao and self.posicao.ignicao is not None
                else "não informada"
            ),
            "segue a rota prevista": (
                {True: "sim", False: "não", None: "não informado"}[self.posicao.em_rota]
                if self.posicao
                else "não informado"
            ),
            "desvio da rota": (
                f"{self.posicao.desvio_km} km"
                if self.posicao and self.posicao.desvio_km is not None
                else "não informado"
            ),
            "eventos correlatos na janela": (
                ", ".join(e.tipo_evento for e in self.eventos_correlatos) or "nenhum"
            ),
            "pânicos deste equipamento em 90 dias": len(panicos),
            "destes, confirmados acidentais pelo operador": len(acidentais),
            "histórico recente": (
                "; ".join(
                    f"{e.momento:%d/%m} {e.tipo_evento}"
                    + (f" → {e.desfecho_operador}" if e.desfecho_operador else "")
                    for e in self.historico_90d[:8]
                )
                or "sem eventos"
            ),
        }


class FonteRastreamento(Protocol):
    """Contrato único. A implementação da Bahrd entra quando houver acesso."""

    async def contexto(self, imei: str, momento: datetime) -> ContextoDoVeiculo: ...
