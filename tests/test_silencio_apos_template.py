"""As três formas de silêncio, e o que cada uma faz.

Até 25/08/2026 só uma delas tinha relógio. A tabela combinada com a Central:

    Silêncio                            Pânico            Demais eventos
    ─────────────────────────────────────────────────────────────────────
    Template entregue, nunca respondeu  5 min → humano    24 h → encerra
    Disse "vou ver" e sumiu             120 s → humano    60 s + 30 s → encerra
    Sumiu no meio, sem avisar           120 s → humano    24 h → encerra

A segunda linha já existia (`esperas_s`). As outras duas não: a notificação
saía, ou a IA perguntava alguma coisa, e se a pessoa não respondesse **nada
acontecia**. A ocorrência travava e sumia do painel um dia depois, sem
desfecho, sem operador e sem entrar na conta da POC — nem no pânico.

O que separa a primeira linha da terceira é quanto silêncio significa. Antes de
a pessoa responder, o silêncio é ambíguo: o celular pode nem ter sido olhado.
Depois que ela provou que está lendo, sumir é sinal — e por isso o pânico
espera 5 minutos no primeiro caso e 2 no segundo.
"""

from __future__ import annotations

import asyncio

import pytest

from central_ia.api.rotas import whatsapp as rota
from central_ia.config import Settings
from central_ia.domain import eventos as catalogo
from central_ia.orchestration.sessao_whatsapp import Sessoes

TELEFONE = "+5541999998888"
DADOS = {"placa": "XYZ4E56", "interlocutor": "Antônio da Silva"}
UM_DIA = 24 * 60 * 60


def _cfg() -> Settings:
    return Settings(oracle_password="x", mysql_password="x", escalonamento_humano_ativo=False)


def _sessao(codigo: str):
    return Sessoes().abrir(TELEFONE, catalogo.por_codigo(codigo), "TEXTO", DADOS)


@pytest.fixture(autouse=True)
def sem_relogio_pendente():
    yield
    for ocorrencia in list(rota._ESPERAS):
        rota.cancelar_espera(ocorrencia)


@pytest.fixture
def nada_sai(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Registra qualquer tentativa de falar com o cliente, sem falar de verdade."""
    enviadas: list[str] = []

    async def _falsa(cfg, para, texto, em_audio=False):  # noqa: ANN001, ARG001
        enviadas.append(texto)
        return True

    monkeypatch.setattr(rota, "_responder", _falsa)
    return enviadas


# ─────────────────────── A tabela, no catálogo ───────────────────────


@pytest.mark.parametrize(
    ("codigo", "sem_resposta", "sem_aviso"),
    [
        ("PANICO", 300, 120),
        # 60 s desde 01/09/2026: silêncio na pergunta da autorização agora faz a
        # IA perguntar de novo, em vez de encerrar calada um dia depois.
        ("REMOCAO_BATERIA", UM_DIA, UM_DIA),
        ("MOVIMENTO_SEM_IGNICAO", UM_DIA, UM_DIA),
        ("VELOCIDADE_EXCEDIDA", UM_DIA, UM_DIA),
    ],
)
def test_os_prazos_combinados(codigo: str, sem_resposta: int, sem_aviso: int) -> None:
    """Se cair, alguém mexeu num prazo de operação — isso passa pela Central."""
    tipo = catalogo.por_codigo(codigo)

    assert tipo.silencio_no_texto_s == sem_resposta
    assert tipo.silencio_sem_aviso_s == sem_aviso


def test_no_panico_esperar_cabe_dentro_da_janela() -> None:
    """A coerência que se quebrou uma vez e foi consertada em 25/08/2026.

    `janela_s` é o prazo até o escalonamento obrigatório, e o modelo lê esse
    número no contexto de toda conversa. Esperar mais do que ele seria instruir
    o modelo com um prazo que o sistema não cumpre.
    """
    tipo = catalogo.PANICO

    assert max(tipo.esperas_s) <= tipo.janela_s
    assert tipo.silencio_sem_aviso_s <= tipo.janela_s


def test_antes_da_primeira_resposta_espera_se_mais() -> None:
    """Silêncio de quem nunca falou é ambíguo; de quem estava falando, não."""
    assert catalogo.PANICO.silencio_no_texto_s > catalogo.PANICO.silencio_sem_aviso_s


# ─────────────────────── O relógio liga ───────────────────────


@pytest.mark.asyncio
async def test_template_liga_o_relogio_em_todo_evento() -> None:
    """Antes só o pânico tinha relógio aqui; agora o caso comum encerra em 24 h.

    Encerrar e não sumir: um caso que desaparece não foi contido nem escalado,
    e some da conta da POC — cuja meta é justamente conter ≥ 50%.
    """
    for codigo in ("PANICO", "REMOCAO_BATERIA"):
        sessao = _sessao(codigo)
        rota.vigiar_silencio_apos_template(_cfg(), sessao)

        assert sessao.ocorrencia_id in rota._ESPERAS, codigo
        assert any("Sem resposta em" in p.descricao for p in sessao.trilha), codigo


@pytest.mark.asyncio
async def test_a_trilha_diz_o_que_vai_acontecer() -> None:
    """O operador que abrir a ocorrência precisa saber que há relógio correndo.

    Sem isso, o encerramento aparece do nada horas depois e ninguém liga uma
    coisa à outra.
    """
    panico = _sessao("PANICO")
    rota.vigiar_silencio_apos_template(_cfg(), panico)
    bateria = _sessao("REMOCAO_BATERIA")
    rota.vigiar_silencio_apos_template(_cfg(), bateria)

    assert any("5 min" in p.descricao and "operador" in p.descricao for p in panico.trilha)
    assert any("24 h" in p.descricao and "encerra com" in p.descricao for p in bateria.trilha)


def test_sessao_ja_encerrada_nao_ganha_relogio() -> None:
    sessao = _sessao("PANICO")
    sessao.encerrar("encerrada_pela_ia", desfecho="acionamento_acidental_confirmado")

    rota.vigiar_silencio_apos_template(_cfg(), sessao)

    assert sessao.ocorrencia_id not in rota._ESPERAS


# ─────────────────────── O relógio vence ───────────────────────


@pytest.mark.asyncio
async def test_panico_sem_resposta_vai_para_o_humano(nada_sai: list[str]) -> None:
    """Sai das mãos da IA. **E não é encerrando.**

    ⚠️ **Mudou em 02/09/2026.** Antes o pânico sem resposta era encerrado, e a
    asserção aqui era `sessao.encerrada`. O que o teste queria dizer está no
    nome e na mensagem: a ocorrência não pode continuar em "IA está fazendo".
    Encerrar era um jeito de conseguir isso, e era o jeito errado — o caso saía
    de "precisa de você" e ia para os encerrados, onde ninguém volta a olhar.

    O que se exige agora é o que sempre importou: a IA solta o caso, o motivo
    fica escrito, e **ele continua aberto** esperando uma pessoa.
    """
    sessao = _sessao("PANICO")

    await rota._vigiar_silencio(_cfg(), sessao, 0, "sem resposta")

    assert sessao.escalada, "a ocorrência continuou em 'IA está fazendo'"
    assert not sessao.encerrada, "um pânico não pode encerrar sem alguém olhar"
    assert any("silêncio aqui não é ausência" in p.descricao for p in sessao.trilha)
    assert any("Aguardando uma pessoa" in p.descricao for p in sessao.trilha)


@pytest.mark.asyncio
async def test_evento_comum_insiste_quando_espera_a_autorizacao(
    nada_sai: list[str],
) -> None:
    """⚠️ **Mudou em 01/09/2026, e só nesta pergunta.**

    A conversa parava exatamente na pergunta que gera a tratativa e o caso
    morria sem desfecho. Agora a IA volta a perguntar primeiro — **mas só aqui**:
    insistir em toda pergunta seria a central cutucando quem não quis responder.
    """
    sessao = _sessao("MOVIMENTO_SEM_IGNICAO")
    sessao.registrar_ia("Posso deixar os avisos desconsiderados enquanto...", 0.0)

    await rota._vigiar_silencio(_cfg(), sessao, 0, "sem resposta")

    assert not sessao.encerrada, "encerrou sem ao menos tentar de novo"
    assert sessao.aguardando, "não agendou a retomada"


@pytest.mark.asyncio
async def test_nas_outras_perguntas_encerra_como_sempre(nada_sai: list[str]) -> None:
    """Decisão do Leonardo: só a pergunta da autorização merece insistência."""
    sessao = _sessao("MOVIMENTO_SEM_IGNICAO")
    sessao.registrar_ia("Sabe me dizer até quando fica por lá?", 0.0)

    await rota._vigiar_silencio(_cfg(), sessao, 0, "sem resposta")

    assert sessao.encerrada
    assert not sessao.aguardando


@pytest.mark.asyncio
async def test_esgotadas_as_retomadas_encerra_com_o_desfecho_do_catalogo(
    nada_sai: list[str],
) -> None:
    """A insistência tem fim. Não some: encerra com motivo, e o caso entra em
    Encerrados para auditoria."""
    sessao = _sessao("MOVIMENTO_SEM_IGNICAO")
    sessao.registrar_ia("Posso deixar os avisos desconsiderados enquanto...", 0.0)
    sessao.retomadas = sessao.tipo.retomadas_maximas

    await rota._vigiar_silencio(_cfg(), sessao, 0, "sem resposta")

    assert sessao.encerrada
    assert sessao.desfecho == catalogo.MOVIMENTO_SEM_IGNICAO.desfecho_sem_contato


@pytest.mark.asyncio
async def test_o_fim_por_silencio_e_mudo(nada_sai: list[str]) -> None:
    """**Regra do PB-PANICO.**

    Se o botão foi apertado de verdade, escrever qualquer coisa agora avisa
    quem estiver do lado do motorista que a central percebeu.
    """
    for codigo in ("PANICO", "REMOCAO_BATERIA"):
        await rota._vigiar_silencio(_cfg(), _sessao(codigo), 0, "sem resposta")

    assert nada_sai == [], f"falou com o cliente num fim por silêncio: {nada_sai}"


@pytest.mark.asyncio
async def test_qualquer_movimento_invalida_o_prazo(nada_sai: list[str]) -> None:
    """A guarda é `ultima_em`, e serve às duas pontas.

    Sem ela, um pânico respondido no último segundo iria para o operador
    **mesmo tendo sido atendido**, e o cliente veria a conversa morrer no meio.
    """
    sessao = _sessao("PANICO")

    tarefa = asyncio.create_task(rota._vigiar_silencio(_cfg(), sessao, 0, "sem resposta"))
    await asyncio.sleep(0)  # deixa a corotina anotar a marca e ceder
    sessao.registrar_cliente("tô bem, foi sem querer")
    await tarefa

    assert not sessao.encerrada
    assert nada_sai == []


@pytest.mark.asyncio
async def test_responder_cancela_o_relogio() -> None:
    """`_continuar` cancela incondicionalmente.

    `aguardando` cobre só a retomada, e estes relógios correm fora dela.
    """
    sessao = _sessao("PANICO")
    rota.vigiar_silencio_apos_template(_cfg(), sessao)
    assert sessao.ocorrencia_id in rota._ESPERAS

    rota.cancelar_espera(sessao.ocorrencia_id)

    assert sessao.ocorrencia_id not in rota._ESPERAS


# ─────────────────────── A terceira linha ───────────────────────


@pytest.mark.asyncio
async def test_pergunta_sem_resposta_tambem_liga_relogio() -> None:
    """O caso mais comum de todos, e o último a ganhar tratamento.

    A IA pergunta, a pessoa lê, se distrai e não volta. Não disse "peraí", então
    o modelo não marca `[AGUARDAR]` e o relógio da retomada nunca ligava.
    """
    sessao = _sessao("REMOCAO_BATERIA")

    rota.vigiar_silencio_sem_aviso(_cfg(), sessao)

    assert sessao.ocorrencia_id in rota._ESPERAS
    assert any("24 h" in p.descricao for p in sessao.trilha)


def test_o_turno_normal_liga_o_relogio() -> None:
    """Confere a chamada real, não só a função solta.

    Se alguém mover o `return` e a chamada ficar inalcançável, o buraco volta
    em silêncio — que é exatamente como ele passou despercebido até agora.
    """
    import inspect

    fonte = inspect.getsource(rota._falar)

    assert "vigiar_silencio_sem_aviso(cfg, sessao)" in fonte


@pytest.mark.asyncio
async def test_o_aviso_de_silencio_nao_se_repete_na_trilha() -> None:
    """Leitura do painel em 28/08/2026, numa conversa de sete turnos.

    A mesma linha, *"Sem resposta em 24 h, o caso encerra com
    sem_resposta_apos_tentativas"*, aparecia quatro vezes: uma por mensagem que
    a IA mandou. O rearme está certo, a contagem tem de começar da última fala.
    Anotar de novo é que não estava.

    Trilha é tela de operador. Cada repetição empurra para fora do campo de
    visão o que ele precisa ver, o toque no botão, a causa escolhida, a
    tratativa pedida. Dizer quatro vezes a mesma coisa não informa mais, informa
    menos.
    """
    sessao = _sessao("REMOCAO_BATERIA")

    rota.vigiar_silencio_sem_aviso(_cfg(), sessao)
    rota.vigiar_silencio_sem_aviso(_cfg(), sessao)
    rota.vigiar_silencio_sem_aviso(_cfg(), sessao)

    avisos = [p for p in sessao.trilha if p.descricao.startswith(rota._PREFIXO_DO_AVISO)]

    assert len(avisos) == 1, f"a trilha repetiu o aviso {len(avisos)} vezes"
    assert sessao.ocorrencia_id in rota._ESPERAS, "o relógio continua sendo rearmado"


@pytest.mark.asyncio
async def test_prazo_diferente_volta_a_ser_anotado() -> None:
    """O outro lado: silenciar a repetição não pode silenciar a mudança.

    O primeiro relógio de um pânico dá 5 minutos, o segundo dá 2. Se o operador
    não vir a linha nova, ele lê na tela um prazo que já não vale, e é pior do
    que a repetição que a gente acabou de tirar.

    Por isso a comparação é do texto inteiro, e não da existência de um aviso
    qualquer: prazo ou destino diferente é informação nova.
    """
    sessao = _sessao("PANICO")

    rota.vigiar_silencio_apos_template(_cfg(), sessao)
    rota.vigiar_silencio_sem_aviso(_cfg(), sessao)

    avisos = [p.descricao for p in sessao.trilha if p.descricao.startswith(rota._PREFIXO_DO_AVISO)]

    assert len(avisos) == 2, "o prazo mudou e a trilha tem de dizer"
    assert avisos[0] != avisos[1]
