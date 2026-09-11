"""Quem pede para falar com uma pessoa, fala com uma pessoa.

A IA já sabia escalar sozinha — ela emite a marca quando **conclui** que o caso
é de gente. Mas concluir é julgamento, e julgamento erra: o modelo pode achar
que dá conta, que a pessoa está só desabafando, que vale mais uma pergunta
antes. Em todo o resto essa margem é boa, e é o que faz a POC conter
atendimento.

Pedido explícito de atendente é a única fala do cliente que **não é matéria de
opinião**. Por isso a decisão saiu do modelo e virou código, e por isso estes
testes existem: eles guardam um caminho que precisa ser determinístico.
"""

from __future__ import annotations

import pytest

from central_ia.agent.pedido_de_humano import pediu_humano
from central_ia.api.rotas import whatsapp as rota
from central_ia.domain import eventos as catalogo
from central_ia.orchestration.sessao_whatsapp import Sessao, Sessoes

DADOS = {"placa": "ABC-1234", "interlocutor": "Geraldo da Silva"}


# ─────────────────────────── o que é pedido ───────────────────────────


@pytest.mark.parametrize(
    "frase",
    [
        "quero falar com um atendente",
        "me passa pra um ATENDENTE",
        "queria falar com o operador por favor",
        "tem como falar com uma pessoa?",
        "quero falar com alguém",
        "isso é um robô? não quero falar com robô",
        "prefiro falar com um ser humano",
        "me transfere pra alguém de verdade",
        "quero falar com o supervisor",
        "pode me ligar?",
        "prefiro por telefone",
        "atendimento humano",
    ],
)
def test_pedidos_sao_reconhecidos(frase: str) -> None:
    """Acento, maiúscula e pontuação não podem esconder um pedido."""
    assert pediu_humano(frase) is not None, f"não reconheceu: {frase!r}"


@pytest.mark.parametrize(
    "frase",
    [
        # O caso real de 27/08/2026, com um `é` a mais. Foi ele que mostrou
        # que substring literal não serve para quem escreve dirigindo.
        "Quero falar com algueém ai",
        "kero falar com uma pesoa",
        "quero falar cm alguem ai",
        "quero falar com um oporador",
        "preciso de um superviisor",
        "quero atendimento humanoo",
        # Áudio mal transcrito erra de outro jeito: troca letra e PARTE palavra.
        # Colapsar repetidas não resolve nenhum dos dois — só semelhança.
        "me passa pro atendende",
        "quero falar com o a tendente",
    ],
)
def test_erro_de_digitacao_e_audio_ruim_nao_escondem_o_pedido(frase: str) -> None:
    """Quem escreve isto está dirigindo.

    O cliente digita com uma mão no volante, ou manda áudio e o Deepgram
    entrega "atendende". Nos dois casos a intenção é inequívoca e a grafia não
    é — e exigir grafia certa de quem está no meio de uma ocorrência é exigir a
    coisa errada.
    """
    assert pediu_humano(frase) is not None, f"não reconheceu: {frase!r}"


def test_todo_padrao_literal_e_igual_a_propria_normalizacao() -> None:
    """⚠️ O bug que os dois lados da comparação precisam não ter.

    `pessoa` tem `ss`, que o colapso de repetidas transforma em `pesoa`. O
    texto do cliente chegava normalizado e o padrão não, e "tem como falar com
    uma pessoa" não batia — o teste acima pegou isso na primeira execução.

    Este guarda a invariante em vez do caso: qualquer padrão novo escrito com
    letra dobrada quebra aqui, e não em produção.
    """
    from central_ia.agent import pedido_de_humano as m

    for nome in ("_FORTES", "_RECUSAS", "_OUTRO_CANAL"):
        for padrao in getattr(m, nome):
            assert padrao == m._normalizar(padrao), f"{nome}: {padrao!r} não normalizado"

    for nome in ("_FRACOS", "_VERBOS"):
        bruto = getattr(m, nome)
        assert bruto == m._normalizar(bruto), f"{nome} não está normalizado"


@pytest.mark.parametrize(
    "frase",
    [
        "Sim foi desligado e está em manutenção",
        "a pessoa que dirige o caminhão desligou a chave",
        "alguém mexeu na bateria ontem",
        "vou verificar",
        "Diamante",
        "o caminhão está na oficina até sexta",
        "quem liga pra central sou eu mesmo quando precisa",
        "tem algum problema com o rastreador?",
        "vou atender aqui e já volto",
        "a bateria foi removida pelo mecânico",
        "estou dirigindo agora não posso parar",
    ],
)
def test_conversa_normal_nao_dispara(frase: str) -> None:
    """O outro lado do erro, e ele é real.

    Transferir quem não pediu é tão ruim quanto não transferir quem pediu: some
    com um atendimento que estava indo bem. "pessoa", "alguém" e "central"
    sozinhas na lista fariam exatamente isso — todas aparecem em conversa
    normal, e a última é o nome da própria empresa.
    """
    assert pediu_humano(frase) is None, f"disparou à toa em: {frase!r}"


def test_devolve_a_expressao_e_nao_so_um_sim() -> None:
    """Vai para a trilha: o operador abre o caso sabendo com que palavras."""
    assert pediu_humano("quero falar com um atendente") == "atendente"


# ─────────────────────────── o caminho na rota ───────────────────────────


@pytest.fixture
def sessao() -> Sessao:
    tipo = catalogo.por_codigo("REMOCAO_BATERIA")
    assert tipo is not None
    return Sessoes().abrir("+5541999999999", tipo, "TEXTO", DADOS)


class _Cfg:
    escalonamento_humano_ativo = False
    whatsapp_responder_em_audio = False


@pytest.mark.asyncio
async def test_vai_para_a_fila_humana_mesmo_com_a_chave_desligada(monkeypatch, sessao) -> None:
    """O ponto todo deste caminho.

    `ESCALONAMENTO_HUMANO_ATIVO` está `False` e existe para o caso em que a
    **IA** conclui que precisa de gente: nesta fase não há operador de plantão,
    e encher a fila de casos que ninguém vai olhar é pior do que registrar e
    fechar.

    Aqui o julgamento é de quem está do outro lado. Fechar o caso depois de
    dizer "já estou passando para um operador" seria mentir para o cliente e
    esconder o pedido de quem deveria recebê-lo. Se não houver ninguém olhando
    o painel, **o problema é esse** — e ele precisa aparecer na fila para ser
    resolvido, não sumir para não incomodar.
    """
    monkeypatch.setattr(rota, "_responder", _ok)

    await rota._entregar_a_um_humano(_Cfg(), sessao, "atendente")

    assert sessao.escalada is True, "o caso precisa aparecer na aba do operador"
    assert sessao.encerrada is True
    assert sessao.motivo_encerramento == "pedido_de_atendimento_humano"


@pytest.mark.asyncio
async def test_a_despedida_avisa_a_transferencia_e_usa_o_nome(monkeypatch, sessao) -> None:
    """Quem pediu atendente precisa ouvir três coisas.

    Que foi entendido, que vai acontecer, e que não está sendo largado. A
    despedida do catálogo não serve: aquela fecha um caso resolvido, esta abre
    uma passagem.
    """
    ditas: list[str] = []

    async def _guardar(cfg, para, texto, em_audio=False):  # noqa: ARG001
        ditas.append(texto)
        return True

    monkeypatch.setattr(rota, "_responder", _guardar)

    await rota._entregar_a_um_humano(_Cfg(), sessao, "atendente")

    (frase,) = ditas
    assert "Geraldo" in frase, "só o primeiro nome, e ele precisa estar lá"
    assert "da Silva" not in frase
    assert "operador" in frase.lower()
    # E o cliente vê a frase no painel também, senão o operador acha que a IA
    # largou a conversa no ar.
    assert sessao.falas[-1].texto == frase


@pytest.mark.asyncio
async def test_sem_nome_a_frase_continua_de_pe(monkeypatch) -> None:
    """Nome vem do cadastro da Bahrd, e cadastro tem campo vazio."""
    ditas: list[str] = []

    async def _guardar(cfg, para, texto, em_audio=False):  # noqa: ARG001
        ditas.append(texto)
        return True

    monkeypatch.setattr(rota, "_responder", _guardar)
    tipo = catalogo.por_codigo("REMOCAO_BATERIA")
    assert tipo is not None
    sem_nome = Sessoes().abrir("+5541988888888", tipo, "TEXTO", {"placa": "ABC-1234"})

    await rota._entregar_a_um_humano(_Cfg(), sem_nome, "atendente")

    (frase,) = ditas
    assert frase.startswith("Claro!")
    assert " ," not in frase and "Claro," not in frase


@pytest.mark.asyncio
async def test_o_operador_ve_por_que_o_caso_chegou(monkeypatch, sessao) -> None:
    """A diferença entre "a IA desistiu" e "o cliente pediu" muda o atendimento.

    Quem abre o caso precisa saber que não houve falha nenhuma — a conversa
    estava indo bem e a pessoa preferiu falar com gente.
    """
    monkeypatch.setattr(rota, "_responder", _ok)

    await rota._entregar_a_um_humano(_Cfg(), sessao, "atendente")

    handoff = " ".join(sessao.handoff)
    assert "pediu atendimento humano" in handoff
    assert "Não foi a IA que desistiu" in handoff

    trilha = " ".join(p.descricao for p in sessao.trilha)
    assert "«atendente»" in trilha, "a expressão que disparou precisa estar na trilha"


@pytest.mark.asyncio
async def test_o_modelo_nao_e_chamado(monkeypatch, sessao) -> None:
    """Não há o que perguntar, e perguntar seria insistir.

    Chamar o modelo aqui gastaria turno, custaria dinheiro e abriria a chance
    de ele responder mais uma pergunta a quem acabou de dizer que não quer
    conversar com ele.
    """
    chamadas: list[str] = []

    monkeypatch.setattr(rota, "_responder", _ok)
    monkeypatch.setattr(rota, "_falar", lambda *a, **k: chamadas.append("falou"))

    await rota._continuar(_Cfg(), sessao, "quero falar com um atendente")

    assert chamadas == []
    assert sessao.escalada is True
    # A despedida conta como fala da IA no painel — ela apareceu no celular do
    # cliente. O que não pode existir é custo: custo só sai de chamar o modelo.
    assert sessao.custo_usd == 0.0


@pytest.mark.asyncio
async def test_a_fala_do_cliente_fica_registrada_antes(monkeypatch, sessao) -> None:
    """O operador abre a conversa e lê o pedido com as palavras da pessoa."""
    monkeypatch.setattr(rota, "_responder", _ok)
    monkeypatch.setattr(rota, "_falar", lambda *a, **k: None)

    await rota._continuar(_Cfg(), sessao, "tem como falar com uma pessoa?")

    do_cliente = [f for f in sessao.falas if f.quem == "cliente"]
    assert do_cliente[-1].texto == "tem como falar com uma pessoa?"


async def _ok(*args, **kwargs) -> bool:  # noqa: ARG001
    return True
