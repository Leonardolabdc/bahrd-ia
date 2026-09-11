"""O caminho de um evento, do recebimento ao desfecho.

    evento → política → (triagem prévia) → (atendimento | fila humana) → registro

Três coisas que este módulo protege, e que são o motivo de ele existir separado
do agente:

1. **A elegibilidade não é decidida pela IA.** Quem autoriza é o catálogo
   determinístico (`domain/eventos.py`). O agente só é acionado depois — e
   apenas com o que foi autorizado.
2. **Evento crítico passa por triagem antes de qualquer contato.** Política
   v2.0: a IA trata todo tipo de evento, inclusive pânico, mas em evento
   crítico ela primeiro cruza os dados e estima a probabilidade de o caso ser
   real. Acima de `LIMIAR_ESCALONAMENTO`, o caso vai para o humano **sem
   contato nenhum** — e leva junto o histórico do que a IA já apurou.
3. **Falha vira humano.** Qualquer exceção no caminho do agente resulta em
   escalonamento, nunca em fechamento automático, e nunca em contato. Está
   implementado como `try/except` em volta de cada chamada de modelo.

O limiar é um número da operação, não do modelo: mora em `domain/eventos.py` e
vai para a trilha de auditoria junto de toda decisão que ele produziu.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from central_ia.agent import conversa as agente_conversa
from central_ia.agent import leitura_panico, prompts, triagem_panico
from central_ia.config import Settings
from central_ia.domain import eventos
from central_ia.domain.eventos import LIMIAR_ESCALONAMENTO, POLITICA_VERSAO, TipoEvento
from central_ia.observability.logging import logger
from central_ia.ports.llm import ClienteLLM
from central_ia.ports.rastreamento import ContextoDoVeiculo, FonteRastreamento

log = logger(__name__)

Estado = Literal["ENCERRADA_PELA_IA", "AGUARDANDO_OPERADOR"]


@dataclass
class PassoAuditoria:
    momento: datetime
    ator: Literal["SISTEMA", "POLITICA", "IA"]
    acao: str
    detalhe: str


@dataclass
class Resultado:
    ocorrencia_id: str
    tipo_evento: str
    criticidade: str
    canal: str | None
    estado: Estado
    elegivel_ia: bool
    motivo_inelegibilidade: str | None
    briefing: str
    briefing_gerado_por_ia: bool
    desfecho: str | None = None
    conversa: list[agente_conversa.Turno] = field(default_factory=list)
    auditoria: list[PassoAuditoria] = field(default_factory=list)

    #: O que a IA fez antes de o caso chegar ao humano, em frases curtas.
    #:
    #: A trilha de auditoria já tem tudo, mas ela é longa e vem fechada. Quem
    #: recebe um caso crítico precisa entender em cinco segundos o que já foi
    #: feito — senão refaz do zero, e o tempo que a triagem economizou volta a
    #: ser gasto.
    handoff: list[str] = field(default_factory=list)

    probabilidade_real: int | None = None

    #: Onde o veículo estava. Vem da fonte de rastreamento e alimenta o mapa do
    #: painel. `None` quando a fonte não sabe — e aí o mapa some, em vez de a
    #: tela mostrar um ponto inventado.
    latitude: float | None = None
    longitude: float | None = None
    endereco: str | None = None

    custo_usd: float = 0.0
    politica_versao: str = POLITICA_VERSAO
    prompt_versao: str = field(default_factory=prompts.versao_dos_prompts)


def _agora() -> datetime:
    return datetime.now(UTC)


def _anotar_posicao(resultado: Resultado, contexto: ContextoDoVeiculo) -> None:
    """Copia a posição para o resultado, se a fonte souber onde o veículo está."""
    if contexto.posicao is None:
        return
    resultado.latitude = contexto.posicao.latitude
    resultado.longitude = contexto.posicao.longitude
    resultado.endereco = contexto.posicao.endereco


class Pipeline:
    def __init__(self, cfg: Settings, llm: ClienteLLM, fonte: FonteRastreamento) -> None:
        self._cfg = cfg
        self._llm = llm
        self._fonte = fonte

    async def processar(
        self, ocorrencia_id: str, codigo_evento: str, imei: str
    ) -> Resultado:
        tipo = eventos.por_codigo(codigo_evento)
        trilha: list[PassoAuditoria] = [
            PassoAuditoria(_agora(), "SISTEMA", "EVENTO_RECEBIDO", f"{codigo_evento} · {imei}")
        ]

        # Fora do catálogo nunca vira atendimento automático — desconhecido é
        # humano por omissão, não por engano.
        if tipo is None:
            trilha.append(
                PassoAuditoria(
                    _agora(), "POLITICA", "FORA_DE_ESCOPO", f"'{codigo_evento}' não catalogado"
                )
            )
            return Resultado(
                ocorrencia_id=ocorrencia_id,
                tipo_evento=codigo_evento,
                criticidade="ALTA",
                canal=None,
                estado="AGUARDANDO_OPERADOR",
                elegivel_ia=False,
                motivo_inelegibilidade="Tipo de evento fora do catálogo",
                briefing="Evento não reconhecido pela política. Encaminhado ao operador.",
                briefing_gerado_por_ia=False,
                auditoria=trilha,
            )

        if tipo.exige_triagem_previa:
            return await self._triar_e_decidir(ocorrencia_id, tipo, imei, trilha)
        if tipo.elegivel_ia:
            return await self._conduzir(ocorrencia_id, tipo, imei, trilha)
        return await self._encaminhar_com_leitura(ocorrencia_id, tipo, imei, trilha)

    # ═══════════════ evento crítico — triagem antes de qualquer contato ═══════

    async def _triar_e_decidir(
        self, ocorrencia_id: str, tipo: TipoEvento, imei: str, trilha: list[PassoAuditoria]
    ) -> Resultado:
        trilha.append(
            PassoAuditoria(
                _agora(),
                "POLITICA",
                "TRIAGEM_OBRIGATORIA",
                f"evento crítico · nenhum contato antes de classificar · "
                f"limiar {LIMIAR_ESCALONAMENTO}% · política {POLITICA_VERSAO}",
            )
        )

        contexto = await self._fonte.contexto(imei, _agora())
        trilha.append(
            PassoAuditoria(
                _agora(),
                "SISTEMA",
                "CONTEXTO_CONSULTADO",
                f"{len(contexto.historico_90d)} evento(s) em 90 dias · "
                f"{len(contexto.eventos_correlatos)} correlato(s) na janela",
            )
        )

        resultado = Resultado(
            ocorrencia_id=ocorrencia_id,
            tipo_evento=tipo.rotulo,
            criticidade=tipo.criticidade,
            canal=None,
            estado="AGUARDANDO_OPERADOR",
            elegivel_ia=True,
            motivo_inelegibilidade=None,
            briefing="",
            briefing_gerado_por_ia=False,
            auditoria=trilha,
        )
        _anotar_posicao(resultado, contexto)

        try:
            triagem, custo = await triagem_panico.classificar(
                self._llm, contexto.resumo_para_triagem()
            )
        except Exception as erro:  # noqa: BLE001 — falha vira humano, princípio 2
            log.warning("triagem_falhou", ocorrencia=ocorrencia_id, erro=str(erro))
            trilha.append(
                PassoAuditoria(
                    _agora(), "SISTEMA", "TRIAGEM_INDISPONIVEL", f"{type(erro).__name__}"
                )
            )
            leitura, por_ia, custo_leitura = await self._leitura(tipo, contexto)
            resultado.briefing = leitura
            resultado.briefing_gerado_por_ia = por_ia
            resultado.handoff = [
                "A triagem automática falhou. Nenhum contato foi feito.",
                "O que segue é leitura de telemetria, sem classificação.",
            ]
            # A chamada que falhou também custou: somar aqui evita que o painel
            # mostre US$ 0,00 numa ocorrência que consumiu crédito.
            resultado.custo_usd = custo_leitura
            return resultado

        resultado.custo_usd = custo
        resultado.probabilidade_real = triagem.probabilidade_real
        trilha.append(
            PassoAuditoria(
                _agora(),
                "IA",
                "TRIAGEM",
                f"{triagem.probabilidade_real}% de chance de ser real · "
                f"{triagem.classificacao} · confiança {triagem.confianca} · "
                + " | ".join(triagem.evidencias),
            )
        )

        if triagem.exige_humano:
            return self._entregar_ao_humano(resultado, tipo, triagem, trilha)

        trilha.append(
            PassoAuditoria(
                _agora(),
                "POLITICA",
                "LIBERADO_PARA_CONTATO",
                f"{triagem.probabilidade_real}% < {LIMIAR_ESCALONAMENTO}% — "
                f"a IA conduz o atendimento pelo {tipo.playbook}",
            )
        )
        return await self._conduzir(
            ocorrencia_id, tipo, imei, trilha, resultado=resultado, triagem=triagem
        )

    def _entregar_ao_humano(
        self,
        resultado: Resultado,
        tipo: TipoEvento,
        triagem: triagem_panico.Triagem,
        trilha: list[PassoAuditoria],
    ) -> Resultado:
        """Acima do limiar: o caso é da pessoa, e vai com o trabalho já feito."""
        trilha.append(
            PassoAuditoria(
                _agora(),
                "POLITICA",
                "ENTREGUE_AO_HUMANO",
                f"{triagem.probabilidade_real}% ≥ {LIMIAR_ESCALONAMENTO}% — "
                "nenhum contato automático foi feito",
            )
        )

        resultado.briefing = triagem.justificativa
        resultado.briefing_gerado_por_ia = True
        resultado.motivo_inelegibilidade = (
            f"Triagem estimou {triagem.probabilidade_real}% de chance de ser real "
            f"(limiar {LIMIAR_ESCALONAMENTO}%)"
        )
        resultado.handoff = [
            f"Cruzou telemetria, rota e histórico do equipamento · {tipo.janela_s}s de janela.",
            f"Estimou {triagem.probabilidade_real}% de chance de ser real "
            f"— acima do limiar de {LIMIAR_ESCALONAMENTO}%.",
            "Não ligou, não mandou mensagem: em caso crítico o contato é seu.",
            *(f"Observou: {e}" for e in triagem.evidencias),
        ]
        return resultado

    # ═════════════════ evento sem playbook — só leitura de contexto ═══════════

    async def _encaminhar_com_leitura(
        self, ocorrencia_id: str, tipo: TipoEvento, imei: str, trilha: list[PassoAuditoria]
    ) -> Resultado:
        """Eventos que aguardam definição da Bahrd. Sem playbook não há conversa."""
        trilha.append(
            PassoAuditoria(
                _agora(),
                "POLITICA",
                "SEM_PLAYBOOK",
                f"{tipo.motivo_inelegibilidade} · política {POLITICA_VERSAO}",
            )
        )

        contexto = await self._fonte.contexto(imei, _agora())
        leitura, por_ia, custo = await self._leitura(tipo, contexto)

        resultado = Resultado(
            ocorrencia_id=ocorrencia_id,
            tipo_evento=tipo.rotulo,
            criticidade=tipo.criticidade,
            canal=None,
            estado="AGUARDANDO_OPERADOR",
            elegivel_ia=False,
            motivo_inelegibilidade=tipo.motivo_inelegibilidade,
            briefing=leitura,
            briefing_gerado_por_ia=por_ia,
            handoff=[
                "Leu o contexto do veículo. Não houve contato — este evento ainda "
                "não tem procedimento definido com a Bahrd.",
            ],
            auditoria=trilha,
            custo_usd=custo,
        )
        _anotar_posicao(resultado, contexto)
        return resultado

    async def _leitura(
        self, tipo: TipoEvento, contexto: ContextoDoVeiculo
    ) -> tuple[str, bool, float]:
        try:
            return await leitura_panico.gerar(self._llm, tipo, contexto.resumo_para_triagem())
        except Exception:  # noqa: BLE001
            return ("Leitura automática indisponível. Consulte a telemetria.", False, 0.0)

    # ══════════════════════════ a IA conduz o atendimento ═════════════════════

    async def _conduzir(
        self,
        ocorrencia_id: str,
        tipo: TipoEvento,
        imei: str,
        trilha: list[PassoAuditoria],
        *,
        resultado: Resultado | None = None,
        triagem: triagem_panico.Triagem | None = None,
    ) -> Resultado:
        canal = tipo.cascata_canais[0]
        trilha.append(
            PassoAuditoria(
                _agora(),
                "POLITICA",
                "LIBERADO_PARA_IA",
                f"playbook {tipo.playbook} · canal {canal} · janela {tipo.janela_s}s · "
                f"política {POLITICA_VERSAO}",
            )
        )

        contexto = await self._fonte.contexto(imei, _agora())
        dados = {
            "placa": contexto.ficha.placa,
            "interlocutor": contexto.ficha.motorista or "o motorista",
            "posição": (contexto.posicao.endereco or "") if contexto.posicao else "",
        }

        if resultado is None:
            resultado = Resultado(
                ocorrencia_id=ocorrencia_id,
                tipo_evento=tipo.rotulo,
                criticidade=tipo.criticidade,
                canal=canal,
                estado="AGUARDANDO_OPERADOR",
                elegivel_ia=True,
                motivo_inelegibilidade=None,
                briefing="",
                briefing_gerado_por_ia=False,
                auditoria=trilha,
            )
        else:
            resultado.canal = canal

        _anotar_posicao(resultado, contexto)

        if triagem is not None:
            resultado.handoff = [
                f"Cruzou telemetria, rota e histórico antes de falar com alguém · "
                f"estimou {triagem.probabilidade_real}% de chance de ser real.",
                f"Abaixo do limiar de {LIMIAR_ESCALONAMENTO}% — seguiu para o contato.",
                *(f"Observou: {e}" for e in triagem.evidencias),
            ]

        try:
            atendimento = await agente_conversa.gerar(self._llm, tipo, canal, dados)
        except Exception as erro:  # noqa: BLE001 — falha vira humano, princípio 2
            log.warning("atendimento_falhou", ocorrencia=ocorrencia_id, erro=str(erro))
            trilha.append(
                PassoAuditoria(
                    _agora(), "SISTEMA", "ATENDIMENTO_INTERROMPIDO", type(erro).__name__
                )
            )
            resultado.briefing = (
                "O atendimento automático foi interrompido por falha técnica. "
                "Nenhum desfecho foi registrado."
            )
            resultado.handoff.append("O atendimento caiu no meio. Nenhum desfecho registrado.")
            return resultado

        resultado.conversa = atendimento.turnos
        resultado.custo_usd += atendimento.custo_usd
        trilha.append(
            PassoAuditoria(
                _agora(),
                "IA",
                "ATENDIMENTO",
                f"{len(atendimento.turnos)} turno(s) · canal {canal}",
            )
        )
        resultado.handoff.append(
            f"Conduziu {len(atendimento.turnos)} turno(s) por {canal.lower()}."
        )

        ultima = next(
            (t.fala for t in reversed(atendimento.turnos) if t.quem == "ia"), ""
        )
        resultado.briefing = ultima
        resultado.briefing_gerado_por_ia = True

        # Modo de demonstração: encerra sem passar pelo operador quando a
        # triagem foi decisiva. Só com TODOS os sinais fechando — qualquer
        # ruído mantém o caso na fila humana.
        if (
            self._cfg.panico_autonomo
            and triagem is not None
            and triagem.pode_encerrar_sozinha
            and "alarme_falso_confirmado_por_triagem" in tipo.desfechos_permitidos
        ):
            resultado.estado = "ENCERRADA_PELA_IA"
            resultado.desfecho = "alarme_falso_confirmado_por_triagem"
            trilha.append(
                PassoAuditoria(
                    _agora(),
                    "IA",
                    "DESFECHO",
                    "alarme_falso_confirmado_por_triagem · encerrado sem operador "
                    "(modo PANICO_AUTONOMO)",
                )
            )
            return resultado

        trilha.append(
            PassoAuditoria(
                _agora(),
                "SISTEMA",
                "ENFILEIRADO_PARA_OPERADOR",
                "atendimento gerado para revisão — desfecho automático entra no Sprint 2",
            )
        )
        return resultado
