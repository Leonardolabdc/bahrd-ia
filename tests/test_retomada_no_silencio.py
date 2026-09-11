"""Silêncio na pergunta que decide não pode virar encerramento calado.

**Pedido da operação**, depois de um teste com duas conversas no
mesmo número. Uma fechou; a outra parou exatamente em *"posso deixar os avisos
desconsiderados enquanto ele estiver parado no local?"* — a pergunta que gera a
tratativa — e o sistema esperou **24 h** para encerrar sem desfecho.

A máquina de retomada já existia e resolvia isso. Só que ela era alcançada
apenas quando o modelo marcava `[AGUARDAR]`, e ele só marca quando a pessoa
**anuncia** a pausa. Quem lê e se distrai não anuncia nada, e esse é o caso
mais comum de todos.

⚠️ O pânico continua encerrando calado, e é decisão: se o botão foi apertado de
verdade, escrever agora avisa quem estiver do lado do motorista.
"""

from __future__ import annotations

import pytest

from central_ia.api.rotas import whatsapp as rota
from central_ia.config import Settings
from central_ia.domain import eventos
from central_ia.orchestration.sessao_whatsapp import SESSOES

BATERIA = eventos.por_codigo("REMOCAO_BATERIA")
MOVIMENTO = eventos.por_codigo("MOVIMENTO_SEM_IGNICAO")
PANICO = eventos.por_codigo("PANICO")

TELEFONE = "+5541999999999"


@pytest.fixture(autouse=True)
def _limpar():
    SESSOES.limpar()
    rota._ESPERAS.clear()
    yield
    SESSOES.limpar()
    rota._ESPERAS.clear()


def _cfg() -> Settings:
    return Settings(_env_file=None)


@pytest.fixture(autouse=True)
def nada_sai(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Registra qualquer tentativa de falar com o cliente, sem falar de verdade.

    ⚠️ **Não é só higiene: sem isto o CI quebra e a máquina de quem desenvolve
    não.** Desde 01/09/2026 o fim por silêncio na pergunta da autorização manda
    uma despedida, e `_responder` tenta entregar de verdade. Aqui o `.env` tem
    credencial de Twilio e a chamada só falha na rede; no CI não tem, e a
    exceção subia. Quatro testes verdes localmente, vermelhos lá.
    """
    enviadas: list[str] = []

    async def _falsa(cfg, para, texto, em_audio=False):  # noqa: ANN001, ARG001
        enviadas.append(texto)
        return "wamid.TESTE"

    monkeypatch.setattr(rota, "_responder", _falsa)
    return enviadas


# ─────────────────────── quem fala e quem cala ───────────────────────


def test_bateria_pergunta_de_novo_depois_de_tres_minutos() -> None:
    """O prazo precisa caber no tempo de uma pessoa ler, decidir e digitar.

    ⚠️ Com 60 s não cabia: em 02/09/2026 o cutucão saiu nove segundos antes de
    a resposta chegar. O número fica preso aqui para que encurtá-lo de novo
    quebre um teste, em vez de irritar um cliente.
    """
    assert BATERIA.retoma_no_silencio is True
    assert rota.SILENCIO_NA_AUTORIZACAO_S == 180


def test_movimento_sem_ignicao_tambem() -> None:
    """Mesma conversa de decisão, mesma regra."""
    assert MOVIMENTO.retoma_no_silencio is True
    assert MOVIMENTO.retomadas_maximas == 2


def test_o_panico_continua_calado() -> None:
    """⚠️ Se o botão foi apertado de verdade, escrever avisa quem está do lado.

    É a razão de o `_vigiar_silencio` ter sido escrito sem mandar mensagem, e
    ligar a retomada nele não pode desfazer isso.
    """
    assert PANICO.retoma_no_silencio is False


def test_o_padrao_e_nao_falar() -> None:
    """Evento novo não começa falante por acidente. Quem quiser, opta."""
    novo = eventos.TipoEvento(
        codigo="X", rotulo="X", criticidade="BAIXA", elegivel_ia=False
    )

    assert novo.retoma_no_silencio is False


def test_a_insistencia_tem_fim() -> None:
    """Duas retomadas e encerra. Insistir para sempre é pior que desistir."""
    assert BATERIA.retomadas_maximas == 2
    assert MOVIMENTO.retomadas_maximas == 2


def test_quem_retoma_tem_espera_configurada() -> None:
    """Sem `esperas_s`, `retomadas_maximas` é zero e a retomada nunca acontece:
    a conversa encerraria calada do mesmo jeito, só que com uma flag ligada
    dando a impressão contrária."""
    for tipo in (BATERIA, MOVIMENTO):
        assert tipo.esperas_s, f"{tipo.codigo} retoma no silêncio mas não tem espera"


# ─────────────────── com frota, insiste uma vez só ───────────────────
#
# **Pedido da operação.** Um número com três caminhões em evento
# teria três conversas cutucando a mesma pessoa, duas vezes cada: seis
# mensagens não pedidas e seis turnos de modelo pagos. O custo cresce com o
# número de veículos, e a chance de resposta não.


@pytest.mark.asyncio
async def test_com_um_veiculo_a_insistencia_continua_valendo_duas() -> None:
    sessao = SESSOES.abrir(TELEFONE, BATERIA, "TEXTO", {"placa": "ABC1D23"})
    sessao.registrar_ia("Posso deixar os avisos desconsiderados enquanto...", 0.0)
    sessao.retomadas = 1  # já insistiu uma vez

    await rota._vigiar_silencio(_cfg(), sessao, 0, "sem resposta")

    assert not sessao.encerrada, "com um veículo, a segunda retomada vale"
    assert sessao.aguardando


@pytest.mark.asyncio
async def test_com_dois_veiculos_insiste_so_uma_vez() -> None:
    """⭐ A regra que economiza mensagem e paciência do cliente."""
    sessao = SESSOES.abrir(TELEFONE, BATERIA, "TEXTO", {"placa": "ABC1D23"})
    sessao.registrar_ia("Posso deixar os avisos desconsiderados enquanto...", 0.0)
    SESSOES.abrir(TELEFONE, BATERIA, "TEXTO", {"placa": "XYZ4E56"})
    sessao.retomadas = 1  # já insistiu uma vez

    await rota._vigiar_silencio(_cfg(), sessao, 0, "sem resposta")

    assert sessao.encerrada, "insistiu duas vezes com frota"


@pytest.mark.asyncio
async def test_com_dois_veiculos_nao_insiste_nenhuma_vez() -> None:
    """⭐ **Decisão dele em 01/09/2026:** com frota, a pergunta sai uma vez e
    pronto. Quem está resolvendo outro caminhão não precisa ser cutucado sobre
    este — e quem retoma o assunto é o `_puxar_o_proximo_veiculo`, que fala
    quando a vez chega e sem custar mensagem extra.

    Ele viu o contrário na tela: *"está em loop perguntando se eu quero
    desconsiderar, perguntou 2 vezes"*."""
    sessao = SESSOES.abrir(TELEFONE, BATERIA, "TEXTO", {"placa": "ABC1D23"})
    sessao.registrar_ia("Posso deixar os avisos desconsiderados enquanto...", 0.0)
    SESSOES.abrir(TELEFONE, BATERIA, "TEXTO", {"placa": "XYZ4E56"})

    await rota._vigiar_silencio(_cfg(), sessao, 0, "sem resposta")

    assert sessao.encerrada, "insistiu com frota"
    assert sessao.teto_de_retomadas == 0


# ─────────── o teto só desce, nunca sobe ───────────


@pytest.mark.asyncio
async def test_o_teto_reduzido_nao_volta_quando_a_outra_encerra() -> None:
    """⚠️ **Bug visto em produção em 01/09/2026, no mesmo dia da regra.**

    Duas conversas rodaram juntas, uma encerrou primeiro, e a sobrevivente
    virou "a única viva" no instante seguinte — recuperando o orçamento de duas
    insistências. O cliente levou a mesma pergunta duas vezes.
    """
    sobrevivente = SESSOES.abrir(TELEFONE, BATERIA, "TEXTO", {"placa": "ABC1D23"})
    sobrevivente.registrar_ia("Posso deixar os avisos desconsiderados...", 0.0)
    outra = SESSOES.abrir(TELEFONE, BATERIA, "TEXTO", {"placa": "XYZ4E56"})

    # Primeiro silêncio, com as duas vivas: teto 1, insiste.
    await rota._vigiar_silencio(_cfg(), sobrevivente, 0, "sem resposta")
    assert sobrevivente.teto_de_retomadas == 0
    sobrevivente.aguardando = False
    sobrevivente.retomadas = 1

    outra.encerrar("encerrada_pela_ia", desfecho="veiculo_em_manutencao")

    # Segundo silêncio, agora sozinha. O teto NÃO pode voltar a 2.
    await rota._vigiar_silencio(_cfg(), sobrevivente, 0, "sem resposta")

    assert sobrevivente.teto_de_retomadas == 0
    assert sobrevivente.encerrada, "insistiu de novo depois que a outra fechou"


@pytest.mark.asyncio
async def test_quem_nasceu_sozinha_e_ganha_companhia_tambem_e_freada() -> None:
    """O mínimo vale nos dois sentidos."""
    sessao = SESSOES.abrir(TELEFONE, BATERIA, "TEXTO", {"placa": "ABC1D23"})
    sessao.registrar_ia("Posso deixar os avisos desconsiderados enquanto...", 0.0)

    await rota._vigiar_silencio(_cfg(), sessao, 0, "sem resposta")
    assert sessao.teto_de_retomadas == BATERIA.retomadas_maximas
    sessao.aguardando = False
    sessao.retomadas = 1

    SESSOES.abrir(TELEFONE, BATERIA, "TEXTO", {"placa": "XYZ4E56"})

    await rota._vigiar_silencio(_cfg(), sessao, 0, "sem resposta")

    assert sessao.teto_de_retomadas == 0
    assert sessao.encerrada
