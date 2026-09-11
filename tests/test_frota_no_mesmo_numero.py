"""Um cliente, vários veículos, um telefone só.

**Defeito real, levantado em 01/09/2026** por uma informação do gestor da
Central: *"às vezes um cliente tem uma frota de carros, e cada evento gerado
para carros diferentes vai pro mesmo número cadastrado"*.

O depósito de sessões era indexado só pelo telefone, e `abrir()` **substituía**
a conversa anterior. O caminhão B alarmava no meio do atendimento do caminhão
A, a sessão de A sumia sem aviso, e a resposta seguinte do gestor caía na
conversa errada. A ocorrência de A ficava viva no painel, sem desfecho.

Nada falhava. É o mesmo formato do bug de 24/08 que gerou o
`test_chave_da_sessao.py`, e é por isso que estes testes existem: sem eles,
volta na primeira refatoração que "simplificar" o depósito.
"""

from __future__ import annotations

import pytest

from central_ia.config import Settings
from central_ia.domain import eventos
from central_ia.orchestration.sessao_whatsapp import SESSOES

TELEFONE = "+5541999999999"
BATERIA = eventos.por_codigo("REMOCAO_BATERIA")
MOVIMENTO = eventos.por_codigo("MOVIMENTO_SEM_IGNICAO")


@pytest.fixture(autouse=True)
def limpar():
    SESSOES.limpar()
    yield
    SESSOES.limpar()


def _abrir(placa: str, tipo=BATERIA):
    return SESSOES.abrir(TELEFONE, tipo, "TEXTO", {"placa": placa})


def _cfg() -> Settings:
    return Settings(oracle_password="x", mysql_password="x")


# ─────────────────────── o defeito que isto fecha ───────────────────────


def test_o_segundo_veiculo_nao_apaga_a_conversa_do_primeiro() -> None:
    """O caso do gestor de frota, exatamente como ele acontece.

    Antes da correção, a segunda chamada de `abrir()` gravava por telefone e a
    primeira sessão era descartada. `vivas()` devolvia uma só.
    """
    caminhao_a = _abrir("ABC1D23")
    caminhao_b = _abrir("XYZ4E56")

    vivas = SESSOES.vivas(TELEFONE)
    assert len(vivas) == 2, "o segundo evento apagou a conversa do primeiro"
    assert {s.ocorrencia_id for s in vivas} == {
        caminhao_a.ocorrencia_id,
        caminhao_b.ocorrencia_id,
    }
    assert caminhao_a.viva and caminhao_b.viva


def test_cinco_caminhoes_no_mesmo_numero_dao_cinco_conversas() -> None:
    """Não é um limite de dois. Frota é frota."""
    placas = ["ABC1D23", "XYZ4E56", "GHI7J89", "JKL0M12", "NOP3Q45"]
    for placa in placas:
        _abrir(placa)

    vivas = SESSOES.vivas(TELEFONE)
    assert len(vivas) == 5
    assert {s.dados["placa"] for s in vivas} == set(placas)


def test_a_mais_recente_vem_primeiro() -> None:
    """`ativa()` é o palpite de quem não tem contexto: o último evento lido."""
    _abrir("ABC1D23")
    ultimo = _abrir("XYZ4E56")

    assert SESSOES.vivas(TELEFONE)[0].ocorrencia_id == ultimo.ocorrencia_id
    assert SESSOES.ativa(TELEFONE).ocorrencia_id == ultimo.ocorrencia_id


# ─────────────────────── o roteamento pelo contexto ───────────────────────


def test_o_contexto_da_meta_manda_na_ocorrencia_certa() -> None:
    """⭐ O que faz o cliente de frota funcionar de verdade.

    Tocar num botão do template faz a Meta devolver `context.id` apontando para
    a notificação tocada. Sem isso, responder ao caminhão A depois de o B
    alarmar cairia no B, que é o mais recente.
    """
    caminhao_a = _abrir("ABC1D23")
    caminhao_a.nossas_mensagens.add("wamid.AAA")
    caminhao_b = _abrir("XYZ4E56")
    caminhao_b.nossas_mensagens.add("wamid.BBB")

    # A pessoa toca no botão da notificação do caminhão A, que é a ANTIGA.
    escolhida = SESSOES.por_nossa_mensagem(TELEFONE, "wamid.AAA")

    assert escolhida is not None
    assert escolhida.ocorrencia_id == caminhao_a.ocorrencia_id
    assert escolhida.dados["placa"] == "ABC1D23"
    # E a recência teria errado, que é o motivo de o contexto existir.
    assert SESSOES.ativa(TELEFONE).ocorrencia_id == caminhao_b.ocorrencia_id


def test_sem_contexto_nao_inventa_ocorrencia() -> None:
    """Texto solto não tem `context.id`, e chutar por id vazio seria pior."""
    sessao = _abrir("ABC1D23")
    sessao.nossas_mensagens.add("wamid.AAA")

    assert SESSOES.por_nossa_mensagem(TELEFONE, None) is None
    assert SESSOES.por_nossa_mensagem(TELEFONE, "") is None
    assert SESSOES.por_nossa_mensagem(TELEFONE, "wamid.DESCONHECIDO") is None


def test_contexto_de_conversa_encerrada_nao_ressuscita() -> None:
    """Responder a uma notificação de caso já fechado não reabre o caso.

    O fechamento é do sistema, não da pessoa. Quem responde depois cai no
    caminho de `encerrada_ha_pouco`, que já existia.
    """
    sessao = _abrir("ABC1D23")
    sessao.nossas_mensagens.add("wamid.AAA")
    sessao.encerrar("encerrada_pela_ia", desfecho="veiculo_em_manutencao")

    assert SESSOES.por_nossa_mensagem(TELEFONE, "wamid.AAA") is None


# ─────────────────────── a poda, para não vazar memória ───────────────────────


def test_conversa_encerrada_sai_da_lista_de_vivas() -> None:
    caminhao_a = _abrir("ABC1D23")
    caminhao_b = _abrir("XYZ4E56")
    caminhao_a.encerrar("encerrada_pela_ia", desfecho="veiculo_em_manutencao")

    vivas = SESSOES.vivas(TELEFONE)
    assert [s.ocorrencia_id for s in vivas] == [caminhao_b.ocorrencia_id]


def test_todas_encerradas_nao_deixa_lista_vazia_pendurada() -> None:
    """A chave sai do dicionário quando não sobra nada vivo nela."""
    sessao = _abrir("ABC1D23")
    sessao.encerrar("encerrada_pela_ia", desfecho="veiculo_em_manutencao")

    assert SESSOES.vivas(TELEFONE) == []
    assert SESSOES.ativa(TELEFONE) is None


def test_o_painel_continua_vendo_as_encerradas() -> None:
    """`vivas()` poda; `todas()` não. O painel precisa das duas conversas.

    Uma conversa que some da tela no instante em que termina é uma conversa
    que ninguém consegue conferir.
    """
    caminhao_a = _abrir("ABC1D23")
    _abrir("XYZ4E56")
    caminhao_a.encerrar("encerrada_pela_ia", desfecho="veiculo_em_manutencao")

    assert len(SESSOES.vivas(TELEFONE)) == 1
    assert len(SESSOES.todas()) == 2


# ─────────────────────── o que não pode ter mudado ───────────────────────


def test_numeros_diferentes_seguem_separados() -> None:
    """A correção alarga o que um número comporta, não mistura números."""
    SESSOES.abrir("+5541999999999", BATERIA, "TEXTO", {"placa": "ABC1D23"})
    SESSOES.abrir("+5541988888888", BATERIA, "TEXTO", {"placa": "XYZ4E56"})

    assert len(SESSOES.vivas("+5541999999999")) == 1
    assert len(SESSOES.vivas("+5541988888888")) == 1


def test_as_grafias_do_telefone_continuam_valendo() -> None:
    """A canonização do `test_chave_da_sessao` tem de sobreviver à lista."""
    _abrir("ABC1D23")
    _abrir("XYZ4E56")

    for grafia in ("554199999999", "5541999999999", "whatsapp:+5541999999999"):
        assert len(SESSOES.vivas(grafia)) == 2, f"{grafia} não achou as conversas"


def test_tipos_de_evento_diferentes_no_mesmo_numero() -> None:
    """Frota real não alarma sempre pelo mesmo motivo."""
    bateria = _abrir("ABC1D23", BATERIA)
    movimento = _abrir("XYZ4E56", MOVIMENTO)

    vivas = SESSOES.vivas(TELEFONE)
    assert len(vivas) == 2
    assert {s.tipo.codigo for s in vivas} == {bateria.tipo.codigo, movimento.tipo.codigo}


# ─────────────── o endereço de TODA mensagem, não só do template ───────────────
#
# ⚠️ **Segundo buraco, achado no teste real de 01/09/2026.** A primeira versão
# guardava só o `id` do template de abertura. Funcionava para o primeiro toque
# e falhava depois: a fala da IA e a pergunta com botões ficavam
# inendereçáveis, e retomar a conversa do outro caminhão exigia rolar a tela
# até a notificação original. Ninguém faz isso.


def test_qualquer_mensagem_nossa_endereca_a_conversa() -> None:
    caminhao_a = _abrir("ABC1D23")
    caminhao_a.nossas_mensagens.add("wamid.TEMPLATE_A")
    caminhao_a.nossas_mensagens.add("wamid.FALA_DA_IA")
    caminhao_a.nossas_mensagens.add("wamid.PERGUNTA_COM_BOTOES")
    _abrir("XYZ4E56")  # mais recente, é quem ganharia sem o contexto

    for citada in ("wamid.TEMPLATE_A", "wamid.FALA_DA_IA", "wamid.PERGUNTA_COM_BOTOES"):
        escolhida = SESSOES.por_nossa_mensagem(TELEFONE, citada)
        assert escolhida is not None, f"{citada} não achou a conversa"
        assert escolhida.ocorrencia_id == caminhao_a.ocorrencia_id


def test_o_sentinela_de_envio_sem_id_nunca_vira_endereco() -> None:
    """O Twilio entrega e não devolve id. Registrar o sentinela faria duas
    conversas compartilharem o mesmo "endereço", e o roteamento escolheria a
    primeira que aparecesse — silenciosamente errado."""
    from central_ia.api.rotas.whatsapp import ENVIADO_SEM_ID, anotar_mensagem_enviada

    sessao = _abrir("ABC1D23")
    anotar_mensagem_enviada(sessao, ENVIADO_SEM_ID)
    anotar_mensagem_enviada(sessao, None)

    assert sessao.nossas_mensagens == set()
    assert SESSOES.por_nossa_mensagem(TELEFONE, ENVIADO_SEM_ID) is None


# ─────────────── a placa na fala, que é o que o cliente lê ───────────────


def test_com_um_veiculo_so_a_placa_nao_aparece() -> None:
    """Repetir a placa numa conversa só é burocracia. A persona pede conversa
    de gente, e a pessoa já sabe de que caminhão se trata."""
    from central_ia.api.rotas.whatsapp import com_a_referencia

    sessao = _abrir("ABC1D23")

    assert com_a_referencia(sessao, "Que bom! Qual é o caso?") == "Que bom! Qual é o caso?"


def test_com_dois_veiculos_toda_fala_diz_a_placa() -> None:
    """⭐ O problema que o cliente vê, e não o sistema.

    Duas conversas paralelas caem na MESMA thread do WhatsApp, intercaladas.
    Sem a placa, ele lê "qual desses é o caso?" e não sabe de qual caminhão.
    Observado num teste real em 01/09/2026.
    """
    from central_ia.api.rotas.whatsapp import com_a_referencia

    caminhao_a = _abrir("ABC1D23")
    caminhao_b = _abrir("XYZ4E56")

    assert (
        com_a_referencia(caminhao_a, "Qual é o caso?")
        == "[ABC1D23 · Remoção de bateria] Qual é o caso?"
    )
    assert (
        com_a_referencia(caminhao_b, "Qual é o caso?")
        == "[XYZ4E56 · Remoção de bateria] Qual é o caso?"
    )


def test_a_placa_nao_e_colada_duas_vezes() -> None:
    """O modelo lê as próprias falas no histórico e imita o formato que vê."""
    from central_ia.api.rotas.whatsapp import com_a_referencia

    sessao = _abrir("ABC1D23")
    _abrir("XYZ4E56")

    uma_vez = com_a_referencia(sessao, "Qual é o caso?")

    assert com_a_referencia(sessao, uma_vez) == uma_vez


def test_sem_placa_no_cadastro_nao_inventa_prefixo() -> None:
    from central_ia.api.rotas.whatsapp import com_a_referencia

    sessao = SESSOES.abrir(TELEFONE, BATERIA, "TEXTO", {})
    SESSOES.abrir(TELEFONE, BATERIA, "TEXTO", {})

    assert com_a_referencia(sessao, "Qual é o caso?") == "Qual é o caso?"


def test_a_placa_some_quando_a_outra_conversa_encerra() -> None:
    """Não é estado pegajoso: a ambiguidade acabou, o prefixo sai junto."""
    from central_ia.api.rotas.whatsapp import com_a_referencia

    caminhao_a = _abrir("ABC1D23")
    caminhao_b = _abrir("XYZ4E56")
    assert com_a_referencia(caminhao_a, "Pronto!").startswith("[ABC1D23 ")

    caminhao_b.encerrar("encerrada_pela_ia", desfecho="veiculo_em_manutencao")

    assert com_a_referencia(caminhao_a, "Pronto!") == "Pronto!"


def test_a_mesma_placa_com_dois_eventos_e_separada_pelo_tipo() -> None:
    """⭐ O caso em que a placa sozinha não resolve, e por isso o tipo entra.

    O mesmo caminhão pode ter bateria e pânico ao mesmo tempo. São duas
    conversas, duas decisões e dois desfechos — e sem o tipo do evento o
    cliente leria dois `[AJL2532]` idênticos e escolheria no escuro.

    Decisão do Leonardo em 01/09/2026, revendo o primeiro desenho, que só
    trazia a placa.
    """
    from central_ia.api.rotas.whatsapp import com_a_referencia

    bateria = SESSOES.abrir(TELEFONE, BATERIA, "TEXTO", {"placa": "AJL2532"})
    movimento = SESSOES.abrir(TELEFONE, MOVIMENTO, "TEXTO", {"placa": "AJL2532"})

    do_primeiro = com_a_referencia(bateria, "E aí?")
    do_segundo = com_a_referencia(movimento, "E aí?")

    assert do_primeiro != do_segundo, "duas conversas da mesma placa ficaram iguais"
    assert BATERIA.rotulo in do_primeiro
    assert MOVIMENTO.rotulo in do_segundo


def test_o_rotulo_usa_o_mesmo_texto_do_template() -> None:
    """Não inventa nome de evento. O cliente leu `Remoção de bateria` na
    notificação; ler outra coisa na conversa seria dois nomes para a mesma
    coisa."""
    from central_ia.api.rotas.whatsapp import com_a_referencia

    sessao = _abrir("ABC1D23")
    _abrir("XYZ4E56")

    assert BATERIA.rotulo in com_a_referencia(sessao, "E aí?")
    assert BATERIA.rotulo == "Remoção de bateria"


# ─────────── a placa escrita, que é como a pessoa se corrige ───────────
#
# ⚠️ **Defeito real, 01/09/2026, e custou um atendimento.** Com duas conversas
# vivas, texto digitado caía sempre na mais recente. O Leonardo respondia sobre
# o AKJ4548, tudo ia para o AIO7569, e a IA **encerrou o caso do caminhão
# errado**. Ele escreveu "eu falei da placa akj4548" e isso também foi para o
# AIO7569, porque ninguém lia a placa.


def test_a_placa_escrita_manda_na_conversa() -> None:
    from central_ia.api.rotas.whatsapp import por_placa_citada

    antiga = _abrir("AKJ4548")
    _abrir("AIO7569")  # mais recente, ganharia sem esta leitura

    escolhida = por_placa_citada(TELEFONE, "Eu falei da placa akj4548")

    assert escolhida is not None
    assert escolhida.ocorrencia_id == antiga.ocorrencia_id


def test_a_placa_vale_em_qualquer_grafia() -> None:
    """Ninguém digita placa do jeito que o cadastro guarda."""
    from central_ia.api.rotas.whatsapp import por_placa_citada

    alvo = _abrir("AKJ4548")
    _abrir("AIO7569")

    for escrita in ("akj4548", "AKJ-4548", "AKJ 4548", "é do akj4548 mesmo", "AKJ4548."):
        achada = por_placa_citada(TELEFONE, escrita)
        assert achada is not None, f"não reconheceu {escrita!r}"
        assert achada.ocorrencia_id == alvo.ocorrencia_id


def test_sem_placa_no_texto_nao_decide_nada() -> None:
    """Cai na recência, que é o comportamento de sempre."""
    from central_ia.api.rotas.whatsapp import por_placa_citada

    _abrir("AKJ4548")
    _abrir("AIO7569")

    assert por_placa_citada(TELEFONE, "Fui eu que desliguei") is None
    assert por_placa_citada(TELEFONE, "") is None


def test_duas_conversas_com_a_mesma_placa_nao_decidem_pela_placa() -> None:
    """Citar a placa não desambigua quando as duas têm a mesma. Chutar aqui
    seria repetir o defeito com outra cara."""
    from central_ia.api.rotas.whatsapp import por_placa_citada

    SESSOES.abrir(TELEFONE, BATERIA, "TEXTO", {"placa": "AKJ4548"})
    SESSOES.abrir(TELEFONE, MOVIMENTO, "TEXTO", {"placa": "AKJ4548"})

    assert por_placa_citada(TELEFONE, "é do akj4548") is None


def test_placa_de_conversa_encerrada_nao_reabre() -> None:
    from central_ia.api.rotas.whatsapp import por_placa_citada

    encerrada = _abrir("AKJ4548")
    _abrir("AIO7569")
    encerrada.encerrar("encerrada_pela_ia", desfecho="veiculo_em_manutencao")

    assert por_placa_citada(TELEFONE, "é do akj4548") is None


# ───────── fechou uma, puxa a próxima ─────────
#
# ⭐ **Pedido do Leonardo em 01/09/2026, e a melhor solução do dia.** Ele tinha
# dois eventos abertos, concluiu um, e o outro ficava esperando um relógio
# vencer. A conversa certa é a que um atendente humano faria: "e sobre o
# AJH4554?" — e continuar de onde parou.
#
# Resolve a ambiguidade na raiz em vez de com mais um mecanismo: duas conversas
# paralelas eram o problema inteiro. Fechando uma e puxando a outra, sobra um
# assunto de cada vez.


@pytest.mark.asyncio
async def test_encerrar_uma_puxa_a_outra_do_mesmo_numero(monkeypatch) -> None:
    from central_ia.api.rotas import whatsapp as rota

    falou_sobre: list[str] = []

    async def _falar_falso(cfg, sessao):  # noqa: ANN001, ARG001
        falou_sobre.append(sessao.ocorrencia_id)

    monkeypatch.setattr(rota, "_falar", _falar_falso)

    concluida = _abrir("ABC1D23")
    pendente = _abrir("XYZ4E56")
    concluida.encerrar("encerrada_pela_ia", desfecho="veiculo_em_manutencao")

    await rota._puxar_o_proximo_veiculo(_cfg(), concluida)

    assert falou_sobre == [pendente.ocorrencia_id]


@pytest.mark.asyncio
async def test_com_um_veiculo_so_nao_puxa_nada(monkeypatch) -> None:
    """Só vale quando há vários eventos no mesmo número."""
    from central_ia.api.rotas import whatsapp as rota

    falou_sobre: list[str] = []

    async def _falar_falso(cfg, sessao):  # noqa: ANN001, ARG001
        falou_sobre.append(sessao.ocorrencia_id)

    monkeypatch.setattr(rota, "_falar", _falar_falso)

    unica = _abrir("ABC1D23")
    unica.encerrar("encerrada_pela_ia", desfecho="veiculo_em_manutencao")

    await rota._puxar_o_proximo_veiculo(_cfg(), unica)

    assert falou_sobre == []


@pytest.mark.asyncio
async def test_ao_puxar_a_proxima_o_foco_vai_junto(monkeypatch) -> None:
    """A frase seguinte dela é sobre este caminhão, e ela não precisa dizer a
    placa para isso."""
    from central_ia.api.rotas import whatsapp as rota

    monkeypatch.setattr(rota, "_falar", lambda cfg, sessao: _nada())

    concluida = _abrir("ABC1D23")
    pendente = _abrir("XYZ4E56")
    concluida.encerrar("encerrada_pela_ia", desfecho="veiculo_em_manutencao")

    await rota._puxar_o_proximo_veiculo(_cfg(), concluida)

    assert rota._foco_atual(TELEFONE).ocorrencia_id == pendente.ocorrencia_id


async def _nada() -> None:
    return None


# ───────── o foco gruda no que ela identificou ─────────


def test_o_foco_so_vale_para_o_que_ela_disse() -> None:
    """⚠️ Recência nunca fixa foco. Seria o palpite de volta com outro nome, e
    foi ele que fechou o caminhão errado hoje cedo."""
    from central_ia.api.rotas import whatsapp as rota

    escolhida = _abrir("ABC1D23")
    _abrir("XYZ4E56")

    assert rota._foco_atual(TELEFONE) is None

    rota._fixar_foco(TELEFONE, escolhida)

    assert rota._foco_atual(TELEFONE).ocorrencia_id == escolhida.ocorrencia_id


def test_o_foco_vence() -> None:
    """Cinco minutos depois ela pode ter voltado para outro caminhão."""
    from datetime import UTC, datetime

    from central_ia.api.rotas import whatsapp as rota
    from central_ia.orchestration.sessao_whatsapp import _chave

    sessao = _abrir("ABC1D23")
    _abrir("XYZ4E56")
    rota._fixar_foco(TELEFONE, sessao)
    rota._FOCO[_chave(TELEFONE)] = (
        sessao.ocorrencia_id,
        datetime.now(UTC) - rota.JANELA_DO_FOCO * 2,
    )

    assert rota._foco_atual(TELEFONE) is None


def test_o_foco_de_conversa_encerrada_nao_vale() -> None:
    from central_ia.api.rotas import whatsapp as rota

    sessao = _abrir("ABC1D23")
    _abrir("XYZ4E56")
    rota._fixar_foco(TELEFONE, sessao)
    sessao.encerrar("encerrada_pela_ia", desfecho="veiculo_em_manutencao")

    assert rota._foco_atual(TELEFONE) is None


# ───────── uma conversa de cada vez ─────────
#
# ⚠️ **A metade que faltava, e ela custou um atendimento em 01/09/2026.** O
# cliente tocou nos botões dos dois caminhões, as duas conversas ficaram
# esperando resposta ao mesmo tempo, e o "Fui eu" que ele digitou caiu na
# errada. Ele escreveu "eu disse que fui eu da primeira mensagem da outra
# placa" e a IA, sem entender, encerrou.
#
# Duas perguntas abertas na mesma janela do WhatsApp é o que torna toda
# resposta ambígua. Todo o resto do roteamento é remendo disso.


def test_o_toque_adiado_nasce_vazio() -> None:
    assert _abrir("ABC1D23").toque_adiado is None


def test_o_toque_guardado_sobrevive_ate_a_vez_chegar() -> None:
    """Tocar no botão é dizer "vi este alarme", e isso não pode se perder só
    porque a vez era de outro caminhão."""
    na_fila = _abrir("XYZ4E56")

    na_fila.toque_adiado = "Está tudo bem!"

    assert na_fila.toque_adiado == "Está tudo bem!"


@pytest.mark.asyncio
async def test_ao_puxar_a_proxima_o_toque_guardado_e_aplicado(monkeypatch) -> None:
    """⭐ Sem isto, a ponte perguntaria algo que a pessoa já respondeu."""
    from central_ia.api.rotas import whatsapp as rota

    perguntou_a_causa: list[str] = []

    async def _perguntar_falso(cfg, sessao, rotulo, abertura=""):  # noqa: ANN001, ARG001
        perguntou_a_causa.append(sessao.ocorrencia_id)
        assert abertura, "a volta tem de ser anunciada quando vem da fila"

    monkeypatch.setattr(rota, "_perguntar_a_causa", _perguntar_falso)

    concluida = _abrir("ABC1D23")
    na_fila = _abrir("XYZ4E56")
    na_fila.toque_adiado = rota.BOTAO_TUDO_BEM
    concluida.encerrar("encerrada_pela_ia", desfecho="veiculo_em_manutencao")

    await rota._puxar_o_proximo_veiculo(_cfg(), concluida)

    assert perguntou_a_causa == [na_fila.ocorrencia_id]
    assert na_fila.toque_adiado is None, "o toque foi aplicado e tem de ser consumido"


@pytest.mark.asyncio
async def test_sem_toque_guardado_a_ponte_e_conversada(monkeypatch) -> None:
    """Quem não tocou em nada recebe a ponte escrita pelo modelo."""
    from central_ia.api.rotas import whatsapp as rota

    falou: list[str] = []

    async def _falar_falso(cfg, sessao):  # noqa: ANN001, ARG001
        falou.append(sessao.ocorrencia_id)

    monkeypatch.setattr(rota, "_falar", _falar_falso)

    concluida = _abrir("ABC1D23")
    pendente = _abrir("XYZ4E56")
    concluida.encerrar("encerrada_pela_ia", desfecho="veiculo_em_manutencao")

    await rota._puxar_o_proximo_veiculo(_cfg(), concluida)

    assert falou == [pendente.ocorrencia_id]


@pytest.mark.asyncio
async def test_o_aviso_da_fila_vai_na_conversa_que_ele_tocou(monkeypatch) -> None:
    """⚠️ **Ele tocou no botão do AJJ3663 e recebeu `[AKK7887]` de volta.**

    A primeira versão respondia na conversa em andamento. No WhatsApp isso lê
    como o sistema tendo ido para o evento errado, e no painel a ocorrência
    tocada ficava com o template e mais nada.
    """
    from central_ia.api.rotas import whatsapp as rota

    ditas: list[tuple[str, str]] = []

    async def _dizer_falso(cfg, sessao, texto):  # noqa: ANN001, ARG001
        ditas.append((sessao.ocorrencia_id, texto))
        return True

    monkeypatch.setattr(rota, "_dizer", _dizer_falso)

    em_andamento = _abrir("AKK7887")
    em_andamento.registrar_cliente("Preciso de ajuda!")
    na_fila = _abrir("AJJ3663")

    await rota._fluxo(
        _cfg(), TELEFONE, "Está tudo bem!", {}, "Está tudo bem!", None, "wamid.FILA"
    )

    assert ditas, "não avisou nada"
    ocorrencia, texto = ditas[0]
    assert ocorrencia == na_fila.ocorrencia_id, "avisou na conversa errada"
    assert "AJJ3663" in texto and "AKK7887" in texto, "não disse as duas placas"


def test_o_toque_na_fila_aparece_na_conversa_do_painel() -> None:
    """Sem isto o painel mostrava só o template, e o cliente jurava ter tocado.

    Ele tinha: o toque estava na trilha de auditoria, que ninguém abre.
    """
    na_fila = _abrir("AJJ3663")

    na_fila.registrar_toque_na_fila("Está tudo bem!")

    assert [f.texto for f in na_fila.falas] == ["Está tudo bem!"]


def test_o_toque_na_fila_nao_conta_como_conversa_iniciada() -> None:
    """⚠️ Só na tela. No `historico` do modelo a conversa ainda não começou, e
    `houve_resposta` continua falso — senão esta sessão viraria "em andamento"
    e a fila se embaralharia sozinha."""
    na_fila = _abrir("AJJ3663")
    antes = len(na_fila.historico)

    na_fila.registrar_toque_na_fila("Está tudo bem!")

    assert na_fila.houve_resposta is False
    assert len(na_fila.historico) == antes, "o modelo não pode ver a conversa começar"


@pytest.mark.asyncio
async def test_o_toque_enfileirado_nao_rouba_o_foco(monkeypatch) -> None:
    """⚠️ **Bug visto em produção em 01/09/2026, minutos depois da fila entrar.**

    O foco era fixado assim que o toque chegava por contexto, antes de a fila
    ser checada. O BBD2336 ia para a fila e **levava o foco junto**, então a
    frase seguinte do cliente caía nele em vez de na conversa em andamento:

        21:06:33  BBD2336 → FILA
        21:07:49  resposta dele → BBD2336, por foco   ← era do AJJ3663
    """
    from central_ia.api.rotas import whatsapp as rota

    async def _nada_dito(cfg, sessao, texto):  # noqa: ANN001, ARG001
        return True

    monkeypatch.setattr(rota, "_dizer", _nada_dito)

    em_andamento = _abrir("AJJ3663")
    em_andamento.registrar_cliente("Preciso de ajuda!")
    _abrir("BBD2336")

    await rota._fluxo(
        _cfg(), TELEFONE, "Está tudo bem!", {}, "Está tudo bem!", None, "wamid.FILA"
    )

    foco = rota._foco_atual(TELEFONE)
    assert foco is not None
    assert foco.ocorrencia_id == em_andamento.ocorrencia_id, "a fila roubou o foco"


def test_a_pergunta_da_causa_anuncia_a_volta(monkeypatch) -> None:
    """⚠️ Sem a frase de volta, os botões apareciam do nada logo depois de o
    outro caminhão fechar, e quem lê não entende que o assunto mudou.

    O rótulo `[placa · evento]` ajuda, mas ninguém lê rótulo como quem lê uma
    frase."""
    import asyncio

    from central_ia.api.rotas import whatsapp as rota

    enviados: list[str] = []

    class _ClienteFalso:
        async def enviar_botoes(self, para, texto, botoes):  # noqa: ANN001, ARG002
            enviados.append(texto)
            return {"messages": [{"id": "wamid.X"}]}

        async def fechar(self):
            return None

    monkeypatch.setattr(rota, "ClienteMeta", lambda cfg: _ClienteFalso())  # noqa: ARG005

    sessao = _abrir("KKJ7874")
    asyncio.run(
        rota._perguntar_a_causa(
            _cfg(), sessao, "Está tudo bem!", abertura="Voltando ao KKJ7874:"
        )
    )

    assert enviados, "não mandou a pergunta"
    assert enviados[0].startswith("Voltando ao KKJ7874:"), enviados[0]


def test_sem_fila_a_pergunta_da_causa_nao_ganha_frase_de_volta(monkeypatch) -> None:
    """Quem nunca esteve na fila não tem para onde "voltar"."""
    import asyncio

    from central_ia.api.rotas import whatsapp as rota

    enviados: list[str] = []

    class _ClienteFalso:
        async def enviar_botoes(self, para, texto, botoes):  # noqa: ANN001, ARG002
            enviados.append(texto)
            return {"messages": [{"id": "wamid.X"}]}

        async def fechar(self):
            return None

    monkeypatch.setattr(rota, "ClienteMeta", lambda cfg: _ClienteFalso())  # noqa: ARG005

    sessao = _abrir("KKJ7874")
    asyncio.run(rota._perguntar_a_causa(_cfg(), sessao, "Está tudo bem!"))

    assert enviados
    assert not enviados[0].startswith("Voltando"), enviados[0]


# ───────── um toque, um risco na conversa ─────────


def test_o_toque_provisorio_sai_quando_o_de_verdade_entra() -> None:
    """⚠️ **Visto no painel em 01/09/2026:** o cliente aparecia tocando duas
    vezes em "Está tudo bem!".

    O toque entra em `falas` quando a conversa vai para a fila, para ela não
    ficar só com o template na tela. Quando a vez chega, `_atender_causa` e
    companhia registram o mesmo toque de novo, aí com histórico do modelo. Um
    toque, dois riscos.
    """
    sessao = _abrir("AAA669")
    sessao.registrar_toque_na_fila("Está tudo bem!")
    assert len(sessao.falas) == 1

    sessao.registrar_cliente("Está tudo bem!")

    assert [f.texto for f in sessao.falas] == ["Está tudo bem!"]
    assert sessao.toque_ja_na_tela is None, "a marca tem de ser consumida"


def test_uma_fala_diferente_nao_e_engolida() -> None:
    """A marca vale para o toque que está na tela, não para tudo que vier."""
    sessao = _abrir("AAA669")
    sessao.registrar_toque_na_fila("Está tudo bem!")

    sessao.registrar_cliente("mudei de ideia")

    assert [f.texto for f in sessao.falas] == ["Está tudo bem!", "mudei de ideia"]


def test_a_ordem_da_conversa_e_preservada() -> None:
    """⚠️ Apagar o toque provisório desordenaria a conversa: a resposta da fila
    entra entre os dois, e a IA passaria a dizer "anotei o alerta" ANTES de a
    pessoa ter tocado."""
    sessao = _abrir("FFF8877")
    sessao.registrar_toque_na_fila("Está tudo bem!")
    sessao.registrar_ia("Anotei o alerta do FFF8877, vamos terminar o outro primeiro.", 0.0)

    sessao.registrar_cliente("Está tudo bem!")

    assert [f.quem for f in sessao.falas] == ["cliente", "ia"]


@pytest.mark.asyncio
async def test_escalar_para_humano_tambem_puxa_o_proximo(monkeypatch) -> None:
    """⚠️ **Visto em 02/09/2026.** Ele tocou nos dois botões, pediu atendente
    humano no primeiro, e o segundo ficou esperando um relógio vencer.

    A ponte estava ligada só no encerramento por desfecho, e escalonamento não
    passa por lá. Agora quem decide é o `_fluxo`, olhando se a conversa
    terminou — vale para qualquer motivo de fechamento.
    """
    from central_ia.api.rotas import whatsapp as rota

    puxados: list[str] = []

    async def _puxar_falso(cfg, encerrada):  # noqa: ANN001, ARG001
        puxados.append(encerrada.ocorrencia_id)

    async def _continuar_falso(cfg, sessao, corpo, **kwargs):  # noqa: ANN001, ARG001
        sessao.encerrar("pedido_de_atendimento_humano")

    monkeypatch.setattr(rota, "_puxar_o_proximo_veiculo", _puxar_falso)
    monkeypatch.setattr(rota, "_continuar", _continuar_falso)

    ativa = _abrir("EBC6595")
    ativa.registrar_cliente("Preciso de ajuda!")
    _abrir("AAA1551")
    # Ele está no meio da conversa do EBC6595, então o foco já está fixado —
    # senão o roteamento pararia para perguntar de qual veículo, que é outro
    # comportamento e tem teste próprio.
    rota._fixar_foco(TELEFONE, ativa)

    await rota._fluxo(_cfg(), TELEFONE, "quero falar com uma pessoa", {})

    assert puxados == [ativa.ocorrencia_id], "escalou e abandonou o outro veículo"


@pytest.mark.asyncio
async def test_conversa_que_continua_nao_puxa_ninguem(monkeypatch) -> None:
    """A ponte é para quando a conversa TERMINA, não a cada mensagem."""
    from central_ia.api.rotas import whatsapp as rota

    puxados: list[str] = []

    async def _puxar_falso(cfg, encerrada):  # noqa: ANN001, ARG001
        puxados.append(encerrada.ocorrencia_id)

    async def _continuar_falso(cfg, sessao, corpo, **kwargs):  # noqa: ANN001, ARG001
        return None

    monkeypatch.setattr(rota, "_puxar_o_proximo_veiculo", _puxar_falso)
    monkeypatch.setattr(rota, "_continuar", _continuar_falso)

    ativa = _abrir("EBC6595")
    ativa.registrar_cliente("Preciso de ajuda!")
    _abrir("AAA1551")
    rota._fixar_foco(TELEFONE, ativa)

    await rota._fluxo(_cfg(), TELEFONE, "foi manutenção", {})

    assert puxados == []
