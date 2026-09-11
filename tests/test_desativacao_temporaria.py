"""Desativação temporária — suprimir alarme não é encerrar o caso.

Vem dos scripts reais da Central (doc 12). Quando o cliente confirma manutenção
ou transporte, o operador **não encerra**:

    "Iremos desconsiderar os eventos enquanto no local."
    "Iremos desconsiderar os eventos durante esse transporte."

Encerrar diz *o caso acabou*; desativar diz *a situação continua, e os próximos
alarmes dela são esperados*. Tratar os dois como o mesmo desfecho faz o veículo
disparar de novo em minutos e alguém atender a mesma coisa outra vez — o custo
que a IA existe para eliminar.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from central_ia.domain import eventos
from central_ia.orchestration.sessao_whatsapp import SESSOES

MOVIMENTO = eventos.por_codigo("MOVIMENTO_SEM_IGNICAO")
BATERIA = eventos.por_codigo("REMOCAO_BATERIA")


@pytest.fixture(autouse=True)
def limpar():
    SESSOES.limpar()
    yield
    SESSOES.limpar()


# ─────────────────────────── o catálogo ───────────────────────────


@pytest.mark.parametrize(
    "desfecho",
    ["reboque_autorizado", "transporte_em_prancha_ou_balsa",
     "veiculo_em_manutencao", "local_e_base_do_cliente"],
)
def test_situacao_que_continua_desativa(desfecho: str) -> None:
    assert eventos.desativa_temporariamente(desfecho)


@pytest.mark.parametrize(
    "desfecho",
    ["falso_positivo_gps", "alarme_falso_confirmado_por_triagem",
     "sem_resposta_apos_tentativas"],
)
def test_caso_que_acabou_nao_desativa(desfecho: str) -> None:
    """Falso positivo e sem resposta encerram de verdade — não há o que suprimir."""
    assert not eventos.desativa_temporariamente(desfecho)


def test_transporte_sem_prazo_informado_cai_no_padrao_de_duas_horas() -> None:
    """⭐ O número é do gestor da Central, repassado em 02/09/2026.

    *"Para movimento com ignição desligada é inativado por 2 horas quando não há
    a confirmação do cliente do tempo em que vai levar o transporte. Caso o
    cliente dê um tempo, é inativado pelo tempo informado. Mas padrão é 2
    horas."*

    Era 1 hora, herdada do texto do script do operador. O padrão da operação é o
    dobro.
    """
    assert eventos.duracao_da_desativacao("reboque_autorizado") == timedelta(hours=2)
    assert eventos.DESATIVACAO_PADRAO_DE_TRANSPORTE == timedelta(hours=2)


def test_o_tempo_que_o_cliente_informa_vence_o_padrao() -> None:
    """Quem sabe quanto dura o transporte é quem está com o veículo."""
    sessao = SESSOES.abrir("+5541999999999", MOVIMENTO, "TEXTO", {})

    sessao.encerrar(
        "encerrada_pela_ia", desfecho="reboque_autorizado", horas_de_desativacao=5
    )

    assert sessao.desativada
    assert sessao.desativada_ate is not None
    faltam = sessao.desativada_ate - datetime.now(UTC)
    assert timedelta(hours=4, minutes=55) < faltam <= timedelta(hours=5)


def test_o_prazo_informado_tem_teto() -> None:
    """⚠️ A conversa não passa das 24 h da Meta.

    Suprimir além disso é prometer o que este atendimento não alcança, e abre a
    porta para o "deixa desativado a semana toda" que ninguém na Central
    autorizaria.
    """
    sessao = SESSOES.abrir("+5541999999998", MOVIMENTO, "TEXTO", {})

    sessao.encerrar(
        "encerrada_pela_ia", desfecho="reboque_autorizado", horas_de_desativacao=500
    )

    assert sessao.desativada_ate is not None
    faltam = sessao.desativada_ate - datetime.now(UTC)
    assert faltam <= eventos.DESATIVACAO_MAXIMA_INFORMADA


def test_prazo_informado_nao_cria_desativacao_onde_nao_havia() -> None:
    """⛔ Só ajusta a duração de quem já suprimia; não transforma desfecho.

    `veiculo_em_manutencao` suprime **até a situação mudar**, sem relógio. Um
    número vindo do modelo não pode virar prazo onde a política diz que não há.
    """
    sessao = SESSOES.abrir("+5541999999997", MOVIMENTO, "TEXTO", {})

    sessao.encerrar(
        "encerrada_pela_ia", desfecho="veiculo_em_manutencao", horas_de_desativacao=3
    )

    assert sessao.desativada
    assert sessao.desativada_ate is None, "sem prazo continua sem prazo"


@pytest.mark.parametrize("desfecho", ["veiculo_em_manutencao", "local_e_base_do_cliente"])
def test_veiculo_parado_nao_tem_prazo(desfecho: str) -> None:
    """*"Enquanto no local"* — sai quando voltar a se mover, não pelo relógio."""
    assert eventos.duracao_da_desativacao(desfecho) is None


# ─────────────────────────── na sessão ───────────────────────────


def test_encerrar_com_transporte_marca_a_desativacao() -> None:
    sessao = SESSOES.abrir("+5541999999999", MOVIMENTO, "TEXTO", {})
    sessao.encerrar("encerrada_pela_ia", desfecho="reboque_autorizado")

    assert sessao.desativada
    assert sessao.desativada_ate is not None


def test_encerrar_com_manutencao_desativa_sem_prazo() -> None:
    sessao = SESSOES.abrir("+5541999999999", BATERIA, "TEXTO", {})
    sessao.encerrar("encerrada_pela_ia", desfecho="veiculo_em_manutencao")

    assert sessao.desativada
    assert sessao.desativada_ate is None


def test_desfecho_comum_nao_desativa() -> None:
    sessao = SESSOES.abrir("+5541999999999", MOVIMENTO, "TEXTO", {})
    sessao.encerrar("encerrada_pela_ia", desfecho="falso_positivo_gps")

    assert not sessao.desativada


def test_encerrar_sem_desfecho_nao_desativa() -> None:
    """Escalonamento fecha sem desfecho — não há o que suprimir."""
    sessao = SESSOES.abrir("+5541999999999", MOVIMENTO, "TEXTO", {})
    sessao.encerrar("escalado_pela_ia")

    assert not sessao.desativada


# ─────────────────────────── o prazo vencendo ───────────────────────────


def test_prazo_vencido_e_visivel() -> None:
    """O operador precisa ver: passou a hora e ninguém confirmou que continua."""
    sessao = SESSOES.abrir("+5541999999999", MOVIMENTO, "TEXTO", {})
    sessao.encerrar("encerrada_pela_ia", desfecho="reboque_autorizado")
    sessao.desativada_ate = datetime.now(UTC) - timedelta(minutes=5)

    assert sessao.desativacao_expirou


def test_dentro_do_prazo_nao_esta_vencido() -> None:
    sessao = SESSOES.abrir("+5541999999999", MOVIMENTO, "TEXTO", {})
    sessao.encerrar("encerrada_pela_ia", desfecho="reboque_autorizado")

    assert not sessao.desativacao_expirou


def test_sem_prazo_nunca_vence() -> None:
    """Manutenção não expira pelo relógio — some quando o veículo se mover."""
    sessao = SESSOES.abrir("+5541999999999", BATERIA, "TEXTO", {})
    sessao.encerrar("encerrada_pela_ia", desfecho="veiculo_em_manutencao")

    assert not sessao.desativacao_expirou


# ─────────── a ocorrência abre a partir da aba de supressão ───────────


def test_a_ficha_diz_ate_quando_esta_suprimido() -> None:
    """⚠️ **A linha que faltava, achada em 03/09/2026.**

    O cartão da aba de supressão passou a abrir a ocorrência, e a ficha não
    dizia a única coisa que aquela aba existe para informar: até quando os
    alarmes estão desligados. Encerrado quer dizer *acabou*; suprimido quer
    dizer *continua acontecendo e é esperado*. Sem o prazo à vista, os dois
    parecem a mesma coisa.
    """
    from central_ia.api.rotas.painel import _ocorrencia_da_sessao

    sessao = SESSOES.abrir("+5541999999999", MOVIMENTO, "TEXTO", {})
    sessao.encerrar(
        "encerrada_pela_ia", desfecho="reboque_autorizado", horas_de_desativacao=3
    )

    assert _ocorrencia_da_sessao(sessao).ficha["Alarmes suprimidos"].startswith("até ")


def test_sem_prazo_a_ficha_nao_inventa_um() -> None:
    """`veiculo_em_manutencao` suprime **enquanto a situação durar**.

    Escrever uma hora aqui seria inventar um fim que ninguém combinou — e o
    operador agiria sobre ele.
    """
    from central_ia.api.rotas.painel import _ocorrencia_da_sessao

    sessao = SESSOES.abrir("+5541999999999", BATERIA, "TEXTO", {})
    sessao.encerrar("encerrada_pela_ia", desfecho="veiculo_em_manutencao")

    assert (
        _ocorrencia_da_sessao(sessao).ficha["Alarmes suprimidos"]
        == "até a situação mudar"
    )


def test_prazo_vencido_aparece_escrito() -> None:
    """É o que o operador precisa ver, então vem escrito e não calculado na tela."""
    from central_ia.api.rotas.painel import _ocorrencia_da_sessao

    sessao = SESSOES.abrir("+5541999999999", MOVIMENTO, "TEXTO", {})
    sessao.encerrar("encerrada_pela_ia", desfecho="reboque_autorizado")
    sessao.desativada_ate = datetime.now(UTC) - timedelta(minutes=5)

    assert "vencido" in _ocorrencia_da_sessao(sessao).ficha["Alarmes suprimidos"]


def test_caso_que_nao_suprime_nao_ganha_a_linha() -> None:
    """Rótulo que sempre diz a mesma coisa é ruído na ficha de quem está sob pressão."""
    from central_ia.api.rotas.painel import _ocorrencia_da_sessao

    sessao = SESSOES.abrir("+5541999999999", MOVIMENTO, "TEXTO", {})
    sessao.encerrar("encerrada_pela_ia", desfecho="falso_positivo_gps")

    assert "Alarmes suprimidos" not in _ocorrencia_da_sessao(sessao).ficha
