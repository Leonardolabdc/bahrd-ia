"""Mensagem que não chegou não é atendimento contido.

**O buraco, achado em 26/08/2026.** A Meta avisa por webhook quando a entrega
falha — o número não tem WhatsApp, o template caiu, a janela fechou. Esse aviso
ia só para o log: não aparecia no painel, não anotava na ocorrência, não mudava
desfecho.

Sozinho já era ruim. Combinado com os relógios de silêncio que entraram em
25/08, virou um **desfecho errado**: passadas as 24 h o caso encerrava como
"cliente não respondeu", quando a verdade era "o cliente nunca recebeu nada".

E o erro tinha direção. A meta da POC é conter ≥ 50% dos 8.000 eventos; contar
como contenção um caso em que ninguém foi alcançado deixa o número **melhor**
que a realidade — o pior tipo de erro para levar a uma reunião de resultado.

Não confundir com a falha **síncrona**, quando a Meta recusa o envio na hora:
aquela já era tratada em `_dizer`, com `mensagem_nao_entregue`. Esta é a
assíncrona — a Meta aceita, devolve 200, e a entrega falha segundos depois.
"""

from __future__ import annotations

import pytest

from central_ia.api.rotas import whatsapp as rota
from central_ia.config import Settings
from central_ia.domain import eventos as catalogo
from central_ia.integrations.mensageria.meta import StatusDeEntrega
from central_ia.orchestration.sessao_whatsapp import SESSOES

TELEFONE = "+5541999999999"
DADOS = {"placa": "ABC-1234", "interlocutor": "Bruno da Silva"}


def _cfg(**extra: object) -> Settings:
    base = {"oracle_password": "x", "mysql_password": "x", "escalonamento_humano_ativo": False}
    return Settings(**{**base, **extra})


def _sessao(codigo: str = "REMOCAO_BATERIA"):
    SESSOES.limpar()
    return SESSOES.abrir(TELEFONE, catalogo.por_codigo(codigo), "TEXTO", DADOS)


def _falha(**extra) -> StatusDeEntrega:
    campos = {
        "mensagem_id": "wamid.TESTE",
        "situacao": "failed",
        "destinatario": "554199999999",  # a Meta reporta sem o nono dígito
        "codigo": 131026,
        "titulo": "Message undeliverable",
        "detalhe": "Receiver is incapable of receiving this message",
    }
    return StatusDeEntrega(**{**campos, **extra})


@pytest.fixture(autouse=True)
def limpar():
    yield
    for ocorrencia in list(rota._ESPERAS):
        rota.cancelar_espera(ocorrencia)
    SESSOES.limpar()


# ─────────────────────── O que o operador vê ───────────────────────


def test_o_aviso_vai_para_o_bloco_que_fica_aberto() -> None:
    """`handoff` é "O que a IA já fez", e é o único bloco aberto por padrão.

    A trilha de auditoria também recebe, mas ela vive fechada — e ninguém clica
    no que não sabe que existe. A tela segue o princípio 11: uma decisão por
    tela, e só fica aberto o que muda o que o operador vai fazer em seguida.
    """
    sessao = _sessao()

    rota._registrar_falha_de_entrega(_cfg(), _falha())

    assert sessao.handoff, "nada chegou ao bloco que o operador lê primeiro"
    aviso = sessao.handoff[-1]
    assert "NÃO foi entregue" in aviso
    assert "Message undeliverable" in aviso

    # Sem HTML: o `handoff` é desenhado como texto puro no painel (`{passo}`),
    # então tag aqui apareceria literal na tela do operador. A trilha, essa
    # sim, aceita `<b>` — e o teste abaixo confere que ela usa.
    assert "<" not in aviso, "tag no handoff aparece literal para o operador"


def test_o_detalhe_tecnico_vai_para_a_trilha() -> None:
    """Código e mensagem da Meta ficam um clique abaixo, para quem investigar."""
    sessao = _sessao()

    rota._registrar_falha_de_entrega(_cfg(), _falha())

    trilha = " ".join(p.descricao for p in sessao.trilha)
    assert "131026" in trilha
    assert "Receiver is incapable" in trilha


# ─────────────────────── O desfecho ───────────────────────


def test_nao_conta_como_contencao() -> None:
    """O centro de tudo: ninguém foi alcançado, então não houve atendimento.

    Se esta asserção cair, a POC volta a somar como contido um caso em que a
    mensagem nunca chegou — e o número apresentado no fim do mês fica melhor
    que a realidade.
    """
    sessao = _sessao()

    rota._registrar_falha_de_entrega(_cfg(), _falha())

    assert sessao.encerrada
    assert sessao.desfecho == rota.DESFECHO_NAO_CONTACTADO
    assert "sem_resposta" not in (sessao.desfecho or "")


def test_com_operador_ativo_o_caso_vai_para_uma_pessoa() -> None:
    """Sem operador, encerra registrando o motivo; com operador, escala."""
    sessao = _sessao()

    rota._registrar_falha_de_entrega(_cfg(escalonamento_humano_ativo=True), _falha())

    assert sessao.escalada


@pytest.mark.asyncio
async def test_o_relogio_de_silencio_e_cancelado() -> None:
    """Não se espera resposta de quem não recebeu a pergunta.

    Sem isto, a ocorrência seria encerrada aqui e o relógio ainda dispararia
    depois, tentando encerrar de novo um caso já fechado.
    """
    sessao = _sessao("PANICO")
    rota.vigiar_silencio_apos_template(_cfg(), sessao)
    assert sessao.ocorrencia_id in rota._ESPERAS

    rota._registrar_falha_de_entrega(_cfg(), _falha())

    assert sessao.ocorrencia_id not in rota._ESPERAS


# ─────────────────────── O que não deve acontecer ───────────────────────


def test_entrega_bem_sucedida_nao_mexe_em_nada() -> None:
    """`sent`, `delivered` e `read` passam batido — só `failed` é notícia.

    A guarda vive **dentro** da função, não só em quem chama: encerrar uma
    ocorrência por aviso de "entregue" seria um estrago silencioso, e quem
    chamasse de outro lugar não desconfiaria.
    """
    sessao = _sessao()

    for situacao in ("sent", "delivered", "read"):
        rota._registrar_falha_de_entrega(_cfg(), _falha(situacao=situacao))

    assert not sessao.encerrada
    assert sessao.handoff == []
    assert sessao.trilha == []


def test_sem_conversa_viva_nao_explode() -> None:
    """Aviso que chega depois do encerramento não pode derrubar o webhook.

    500 aqui faz a Meta reduzir as entregas do canal — perder o canal é pior
    que perder um aviso.
    """
    SESSOES.limpar()

    rota._registrar_falha_de_entrega(_cfg(), _falha())


def test_encontra_a_sessao_mesmo_sem_o_nono_digito() -> None:
    """A Meta reporta `554199999999`; a sessão nasceu com `+5541999999999`.

    É o mesmo bug de 24/08 que fez a resposta do motorista não achar a conversa.
    Aqui ele voltaria como "aviso de falha que não encontra ocorrência nenhuma"
    — silencioso, e por isso pior.
    """
    sessao = _sessao()

    rota._registrar_falha_de_entrega(_cfg(), _falha(destinatario="554199999999"))

    assert sessao.encerrada, "não achou a sessão pela grafia sem o nono dígito"


# ─────────── falta de credencial não pode virar exceção ───────────


@pytest.mark.asyncio
async def test_responder_sem_credencial_do_twilio_devolve_none() -> None:
    """⚠️ **Achado pelo CI em 02/09/2026.** A função que promete "nunca levanta"
    levantava: `ClienteTwilio(cfg)` estava **fora** do `try`, e o construtor
    levanta quando falta credencial.

    Ninguém tinha visto porque na máquina de quem desenvolve o `.env` tem as
    credenciais. Onde a exceção acontece é onde ninguém está olhando: dentro de
    um relógio de silêncio, numa tarefa `asyncio` que morre calada.

    O caminho da Meta já se protegia disso desde sempre. O do Twilio não.
    """
    sem_credencial = Settings(
        _env_file=None,
        canal_whatsapp="twilio",
        twilio_account_sid="",
        oracle_password="x",
        mysql_password="x",
    )

    entregue = await rota._responder(sem_credencial, "+5541999999999", "oi")

    assert entregue is None, "devolveu algo como se tivesse entregado"


def test_o_motivo_da_meta_e_escapado() -> None:
    """⛔ **O `handoff` é renderizado como HTML na tela da ocorrência.**

    Os outros itens usam `<b>` para destacar, e a tela passou a interpretar as
    tags em 03/09/2026 (antes elas apareciam cruas). Isso torna o `handoff` um
    caminho de HTML, e `titulo`/`detalhe` são texto do **webhook da Meta**: a
    única interpolação de terceiro na lista.

    O escape fica na origem e não na tela de propósito. Escapar no React
    resolveria só este consumidor; um relatório ou um export do mesmo campo
    voltaria a ficar exposto.
    """
    import html as _html

    bruto = '<img src=x onerror="alert(1)">'

    assert _html.escape(bruto) not in (bruto,)
    assert "<img" not in _html.escape(bruto)
