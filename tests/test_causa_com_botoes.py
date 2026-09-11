"""O ramo "Está tudo bem!" e os três caminhos de causa.

Desenho dos gestores, doc 19. O cliente confirma que está tudo bem e a pergunta
seguinte é **por quê** — porque "tudo bem" não fecha evento: fecha a causa, e a
causa decide o que a Central faz com o alarme.

Uma remoção de bateria com o cliente tranquilo ainda é um caminhão sem
rastreio. Manutenção suprime naquele local, chave geral pode virar regra
permanente, outro motivo fecha e pronto. Três destinos diferentes atrás da
mesma frase.
"""

from __future__ import annotations

import pytest

from central_ia.agent.prompts import RAIZ_PROMPTS
from central_ia.api.rotas import whatsapp as rota
from central_ia.domain import eventos as catalogo
from central_ia.integrations.mensageria.meta import extrair
from central_ia.orchestration import tratativas
from central_ia.orchestration.sessao_whatsapp import Sessao, Sessoes

DADOS = {"placa": "AKK9832", "interlocutor": "Ana da Silva"}


@pytest.fixture(autouse=True)
def tabela_limpa():
    tratativas.TRATATIVAS.limpar()
    yield
    tratativas.TRATATIVAS.limpar()


@pytest.fixture
def sessao() -> Sessao:
    tipo = catalogo.por_codigo("REMOCAO_BATERIA")
    assert tipo is not None
    return Sessoes().abrir("+5541999999999", tipo, "TEXTO", DADOS)


async def _ok(*args, **kwargs) -> bool:  # noqa: ARG001
    return True


# ─────────────────── o id manda, o rótulo é só texto ───────────────────


def test_o_id_do_botao_chega_separado_do_rotulo() -> None:
    """A distinção que sustenta o roteamento.

    Rótulo é texto que alguém reescreve para caber em 20 caracteres; `id` é
    contrato. Trocar "Em manutenção" por "Na oficina" não pode mudar o
    comportamento do sistema — e só não muda porque a rota decide pelo `id`.
    """
    (recebida,) = extrair(
        {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "from": "5541999999999",
                                        "id": "wamid.X",
                                        "type": "interactive",
                                        "interactive": {
                                            "type": "button_reply",
                                            "button_reply": {
                                                "id": "causa_manutencao",
                                                "title": "Em manutenção",
                                            },
                                        },
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }
    )

    assert recebida.botao_id == "causa_manutencao"
    assert recebida.botao == "Em manutenção"


def test_toda_causa_do_menu_tem_nota_e_cabe_no_limite() -> None:
    """Botão sem nota é botão que leva a lugar nenhum.

    E o limite de 20 caracteres não é sugestão: a Meta recorta, e um rótulo
    cortado na metade fica sem sentido na tela de quem precisa escolher.
    """
    from central_ia.integrations.mensageria.meta import LIMITE_BOTOES, LIMITE_ROTULO_BOTAO

    assert len(rota.CAUSAS) <= LIMITE_BOTOES
    for ident, rotulo in rota.CAUSAS:
        assert ident in rota.NOTA_POR_CAUSA, f"{ident} não tem nota para o modelo"
        assert len(rotulo) <= LIMITE_ROTULO_BOTAO, f"{rotulo!r} não cabe no botão"
        assert rotulo.isascii() or all(ord(c) < 0x2000 for c in rotulo), "emoji no botão"


# ─────────────────────── a pergunta com botões ───────────────────────


@pytest.mark.asyncio
async def test_tudo_bem_pergunta_a_causa_com_tres_botoes(monkeypatch, sessao) -> None:
    enviados: list[tuple[str, list[tuple[str, str]]]] = []

    class _Cliente:
        def __init__(self, cfg) -> None:  # noqa: ARG002
            pass

        async def enviar_botoes(self, para, texto, botoes):  # noqa: ARG002
            enviados.append((texto, botoes))
            return {}

        async def fechar(self) -> None:
            pass

    monkeypatch.setattr(rota, "ClienteMeta", _Cliente)
    monkeypatch.setattr(rota, "_ligar_relogio", lambda *a, **k: None)

    await rota._perguntar_a_causa(object(), sessao, rota.BOTAO_TUDO_BEM)

    (texto, botoes) = enviados[0]
    assert "Ana" in texto
    assert [i for i, _ in botoes] == [
        rota.BOTAO_MANUTENCAO,
        rota.BOTAO_CHAVE_GERAL,
        rota.BOTAO_OUTRO_MOTIVO,
    ]


@pytest.mark.asyncio
async def test_o_modelo_sabe_que_a_pergunta_ja_foi_feita(monkeypatch, sessao) -> None:
    """Senão o turno seguinte repete o que a pessoa acabou de responder tocando.

    Mesmo defeito do template de 25/08, na versão pequena: o modelo não lê o
    que não está no histórico dele, e o que ele não leu, ele refaz.
    """

    class _Cliente:
        def __init__(self, cfg) -> None:  # noqa: ARG002
            pass

        async def enviar_botoes(self, *a, **k):  # noqa: ARG002
            return {}

        async def fechar(self) -> None:
            pass

    monkeypatch.setattr(rota, "ClienteMeta", _Cliente)
    monkeypatch.setattr(rota, "_ligar_relogio", lambda *a, **k: None)

    await rota._perguntar_a_causa(object(), sessao, rota.BOTAO_TUDO_BEM)

    ultimo = sessao.historico[-1]
    assert ultimo.papel == "assistant"
    assert "Enviado com botões" in ultimo.conteudo
    assert "Em manutenção" in ultimo.conteudo
    # O operador vê a pergunta limpa, com as opções ao lado.
    assert sessao.falas[-1].tipo == "botoes"
    assert "Enviado com botões" not in sessao.falas[-1].texto


@pytest.mark.asyncio
async def test_sem_botoes_a_conversa_continua_em_texto(monkeypatch, sessao) -> None:
    """Botão é conveniência; a conversa é o produto.

    Se a Meta recusar a mensagem interativa, cair em texto aberto custa um
    turno a mais para a IA classificar a resposta — e não custa o atendimento.
    Deixar o cliente sem resposta custaria.
    """
    from central_ia.integrations.mensageria.meta import MetaIndisponivel

    falou: list[str] = []

    class _Quebrado:
        def __init__(self, cfg) -> None:  # noqa: ARG002
            pass

        async def enviar_botoes(self, *a, **k):  # noqa: ARG002
            raise MetaIndisponivel("HTTP 400")

        async def fechar(self) -> None:
            pass

    async def _registrar(cfg, s):  # noqa: ARG001
        falou.append(s.ocorrencia_id)

    monkeypatch.setattr(rota, "ClienteMeta", _Quebrado)
    monkeypatch.setattr(rota, "_falar", _registrar)

    await rota._perguntar_a_causa(object(), sessao, rota.BOTAO_TUDO_BEM)

    assert falou == [sessao.ocorrencia_id], "a IA precisa perguntar de outro jeito"


# ─────────────────────── cada causa leva a seu lugar ───────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("ident", "tem_de_dizer"),
    [
        (rota.BOTAO_MANUTENCAO, "passo 4 do seu playbook"),
        (rota.BOTAO_CHAVE_GERAL, "passo 4b do seu playbook"),
        (rota.BOTAO_OUTRO_MOTIVO, "PRECISA escrever"),
    ],
)
async def test_cada_causa_instrui_o_modelo(monkeypatch, sessao, ident, tem_de_dizer) -> None:
    monkeypatch.setattr(rota, "_falar", lambda *a, **k: _ok())

    await rota._atender_causa(object(), sessao, ident, "rótulo")

    assert sessao.causa_escolhida == ident
    assert tem_de_dizer in sessao.historico[-1].conteudo
    # A nota é andaime: na tela do operador ela seria ruído.
    assert sessao.falas[-1].texto == "rótulo"


@pytest.mark.asyncio
async def test_manutencao_pergunta_a_data_sem_deixar_ela_limitar(monkeypatch, sessao) -> None:
    """Dois gestores, duas decisões opostas, e a síntese das duas.

    **Central:** não perguntar a data. *"O cliente informa que
    fica em manutenção até as 17h, chega 18h40, gera outra remoção, e ele
    recebe nova notificação e tem de confirmar de novo."* Data prometida por
    cliente é estimativa, e oficina atrasa.

    **Outro gestor, 27/08:** perguntar a data. Ele testou e sentiu falta.

    Os dois têm razão sobre coisas diferentes: um quer **saber** quando o
    veículo sai, o outro não quer que a proteção **acabe** numa data que vai
    furar. Dá para ter as duas, e é o que está aqui: a IA pergunta a data, e a
    proteção continua presa ao local.

    A linha que separa as duas intenções é a proibição de prometer que os
    avisos voltam na data. É ela que impede a síntese de virar o problema que o
    primeiro gestor descreveu.
    """
    monkeypatch.setattr(rota, "_falar", lambda *a, **k: _ok())

    await rota._atender_causa(object(), sessao, rota.BOTAO_MANUTENCAO, "Em manutenção")

    # ⚠️ A regra vive no PLAYBOOK, e não na nota do botão. A diferença custou um
    # atendimento em 28/08/2026: o cliente entrou por «Preciso de ajuda» e
    # chegou em manutenção conversando. A nota do botão nunca se aplicou, e a IA
    # encerrou sem perguntar a data nem pedir autorização, gerando a supressão
    # de alarme de um veículo que ninguém autorizou a suprimir.
    #
    # O botão é atalho. O playbook é onde a regra tem de estar, porque ele é
    # lido nos dois caminhos.
    playbook = (RAIZ_PROMPTS / "playbooks" / "PB-BATERIA.md").read_text(encoding="utf-8")

    assert "até quando o veículo fica em manutenção" in playbook, "o gestor quer a data"
    # ⚠️ A frase fala do VEÍCULO e do LUGAR, e nunca "enquanto ele estiver aí":
    # "aí" é onde a PESSOA está, e ela pode estar em casa enquanto o veículo
    # passa a semana em manutenção. Observação da operação, lendo
    # a IA dizer "aí" para um cliente que não estava lá.
    plano = playbook.replace("\n", " ")
    assert "enquanto ele estiver parado no local da manutenção" in plano
    assert "Nunca diga \"enquanto ele estiver aí\"" in plano
    assert "Nunca prometa que os avisos voltam na data" in playbook
    assert "Sem essa autorização você não encerra com `veiculo_em_manutencao`" in plano
    assert "não importa se" in playbook, "a regra precisa valer nos dois caminhos"
    # E não saber a data não bloqueia nada: a supressão nunca dependeu dela.
    assert "Se não souber, siga em frente sem insistir" in playbook.replace("\n", " ")


@pytest.mark.asyncio
async def test_a_frase_do_fim_da_protecao_e_prescrita(monkeypatch, sessao) -> None:
    """"Assim que ele saltar daí" — conversa real de 27/08/2026.

    A nota dizia *o que* explicar e deixava o *como* aberto, e nessa folga o
    modelo inventou. "Saltar daí" não é português de ninguém, e é justamente a
    frase que o cliente precisa entender de primeira: é ela que diz que a
    proteção acaba quando o caminhão sair da oficina.

    Prescrever a frase é abrir mão de naturalidade num ponto só, e vale a
    troca: aqui clareza importa mais do que soar espontâneo.
    """
    monkeypatch.setattr(rota, "_falar", lambda *a, **k: _ok())

    await rota._atender_causa(object(), sessao, rota.BOTAO_MANUTENCAO, "Em manutenção")

    playbook = (RAIZ_PROMPTS / "playbooks" / "PB-BATERIA.md").read_text(encoding="utf-8")

    assert "os avisos voltam automaticamente" in playbook
    assert "Não invente outro jeito de dizer" in playbook


def test_a_ia_repete_a_data_que_o_cliente_deu() -> None:
    """Leitura da operação, no atendimento que rodou certo.

    O cliente disse *"acho q até quarta que vem"* e a IA respondeu só
    *"Entendi."* antes de pedir a autorização. Não está errado, e não serve: o
    cliente acabou de dar uma informação e não tem como saber se ela chegou a
    algum lugar.

    A instrução antiga dizia "anote na sua resposta seguinte", e "anote" o
    modelo leu como anotar em algum lugar que não é a conversa. Agora ela manda
    **repetir a data com as palavras dele**, e traz o exemplo pronto.
    """
    playbook = (RAIZ_PROMPTS / "playbooks" / "PB-BATERIA.md").read_text(encoding="utf-8")
    plano = playbook.replace("\n", " ")

    assert "repita a data na resposta seguinte, com as palavras dele" in plano
    assert "«Entendi, até quarta então.»" in plano
    # E o contraexemplo, porque é ele que o modelo produziu sozinho.
    assert '"Entendi."' in playbook
    assert "não conta ao cliente que a Central anotou" in plano


def test_o_que_devolve_os_avisos_e_o_veiculo_se_mover() -> None:
    """Leitura da operação, num atendimento que rodou certo.

    A IA disse *"quando ele sair da manutenção, os avisos voltam
    automaticamente"*, e a frase é bonita e está errada. A tratativa que sai
    daqui é `INATIVAR_ENQUANTO_NO_LOCAL`: a Central desconsidera os eventos
    daquele veículo **enquanto ele estiver naquele lugar**, e é o movimento que
    liga tudo de volta.

    O mecânico terminar o serviço não é um sinal que chegue ao nosso sistema.
    Se o veículo ficar parado no pátio da oficina mais dois dias depois de
    pronto, os avisos continuam desconsiderados, e o cliente que ouviu a frase
    antiga acha que estão de volta. É a mesma classe da promessa por data, com
    o gatilho trocado.

    A frase agora nomeia as duas pontas: o veículo **parado no local** e o
    veículo **voltando a se movimentar**.
    """
    playbook = (RAIZ_PROMPTS / "playbooks" / "PB-BATERIA.md").read_text(encoding="utf-8")
    plano = playbook.replace("\n", " ")

    assert "Quando ele voltar a se movimentar, os avisos voltam" in plano
    assert "quando ele sair da manutenção, os avisos voltam" not in plano.lower(), (
        "o gatilho é o movimento, não o fim do serviço"
    )
    assert "O que devolve os avisos é o veículo se mover" in playbook


@pytest.mark.asyncio
async def test_a_chave_geral_nao_usa_jargao_da_central(monkeypatch, sessao) -> None:
    """"Regra de base" é nome interno. O cliente não sabe o que é.

    Mesmo risco do "saltar daí", pego antes de acontecer: se o modelo repetir o
    termo do playbook, o cliente ouve uma proposta que não entende e responde
    "não" por precaução — e a Central perde a supressão que resolveria o caso.
    """
    monkeypatch.setattr(rota, "_falar", lambda *a, **k: _ok())

    await rota._atender_causa(object(), sessao, rota.BOTAO_CHAVE_GERAL, "Desliguei a chave")

    # A regra vive no PLAYBOOK, e não na nota do botão: quem chega na chave
    # geral conversando nunca leria a nota, e foi assim que um atendimento
    # fechou sem oferecer nada em 28/08/2026.
    playbook = (RAIZ_PROMPTS / "playbooks" / "PB-BATERIA.md").read_text(encoding="utf-8")

    assert "NUNCA diga «regra de base»" in playbook
    assert "nesse mesmo lugar e horário" in playbook
    # A regra precisa valer nos dois caminhos, e o texto diz isso.
    assert "por um botão ou" in playbook


# ─────────────────── a decisão vira pedido ao sistema da Bahrd ───────────────────


def test_manutencao_pede_supressao_presa_ao_local(sessao) -> None:
    rota._pedir_tratativas(sessao, "veiculo_em_manutencao", "mensagem longa o bastante aqui")

    acoes = [t.acao for t in tratativas.TRATATIVAS.pendentes()]
    assert tratativas.Acao.INATIVAR_ENQUANTO_NO_LOCAL in acoes
    assert tratativas.Acao.FINALIZAR_EVENTO in acoes


def test_o_operador_ve_que_ficou_combinado_e_nao_executado(sessao) -> None:
    """A aba "A executar" foi removida em 27/08, e isto é o que sobrou dela.

    A operação perguntou se ela era mesmo necessária, já que a API da Bahrd vai
    tratar tudo quando existir. Ele tinha razão: uma aba que fica vazia para
    sempre depois da integração é tela morta, e nesta fase ninguém está de
    plantão para executar nada à mão.

    O que **não** podia sumir é o aviso, e o motivo é o cliente e não o
    registro: a IA acabou de prometer que os eventos deste caminhão seriam
    desconsiderados. Se ninguém executar, ele dispara de novo em minutos — e o
    cliente, que achou que tinha resolvido, recebe outra notificação. Quem
    abrir a ocorrência repetida precisa entender na hora por que ela voltou.

    Por isso vai no `handoff`, que o painel abre, e não na trilha, que fica
    fechada por padrão.
    """
    rota._pedir_tratativas(sessao, "veiculo_em_manutencao", "mensagem longa o bastante aqui")

    aviso = " ".join(sessao.handoff)
    assert "ainda não executado" in aviso
    assert "enquanto ele estiver neste local" in aviso
    assert "não existe" in aviso, "o operador precisa saber por que está parado"


def test_chave_geral_pede_regra_de_base(sessao) -> None:
    rota._pedir_tratativas(
        sessao, "chave_geral_com_regra_autorizada", "mensagem longa o bastante aqui"
    )

    acoes = [t.acao for t in tratativas.TRATATIVAS.pendentes()]
    assert tratativas.Acao.CRIAR_REGRA_DE_BASE in acoes


def test_chave_geral_sem_autorizacao_nao_cria_regra_permanente(sessao) -> None:
    """⚠️ Regra de base vale para SEMPRE, e nasceu sem ninguém pedir.

    Em 28/08/2026 a IA encerrou como chave geral sem oferecer nada, e a
    tratativa `criar_regra_de_base` foi gerada assim mesmo: o mapa ligava o
    desfecho comum à ação permanente.

    Separar os dois desfechos é o que impede isso. A autorização deixa de
    depender de o modelo ter contado direito o que combinou, e passa a ser o
    próprio nome do desfecho que ele escolheu.
    """
    rota._pedir_tratativas(
        sessao, "chave_geral_desligada_pelo_motorista", "mensagem longa o bastante aqui"
    )

    acoes = [t.acao for t in tratativas.TRATATIVAS.pendentes()]
    assert tratativas.Acao.CRIAR_REGRA_DE_BASE not in acoes, "regra permanente sem pedir"

    # Mas a supressão temporária continua: o veículo segue parado no mesmo
    # lugar com a chave desligada, e sem ela dispara de novo em minutos. A
    # diferença entre os dois desfechos é o prazo, não a existência.
    assert tratativas.Acao.INATIVAR_ENQUANTO_NO_LOCAL in acoes


def test_outro_motivo_suprime_no_local_como_os_outros_ramos(sessao) -> None:
    """Este teste já afirmou o contrário, e a razão dele caducou.

    Ele dizia: *"suprimir eventos de um veículo por uma causa que ninguém
    nomeou seria desligar o alarme às cegas"*. Estava certo quando foi escrito,
    e parou de estar: hoje `outro_motivo_confirmado_pelo_cliente` **só fecha
    com o motivo escrito** na mensagem, `MINIMO_DO_MOTIVO` caracteres. A causa
    é nomeada, fica no painel ao lado do caso, e a premissa sumiu.

    O que restou foi tratar pior justamente quem caiu no ramo genérico.
    Atendimento real de 28/08/2026:

        Cliente: Tive que tirar a bateria porque o suporte dela enferrujou e
                 agora precisamos soldar outro
        IA:      Vou registrar aqui que a bateria foi retirada porque o suporte
                 enferrujou e vocês precisam soldar outro. Já tá certo aqui.

    Registrou bonito e encerrou. O veículo seguiu parado no mesmo lugar, com a
    bateria fora, e o alarme ia disparar de novo em minutos.

    A supressão por local é segura aqui porque **se desfaz sozinha** quando o
    veículo se move. Não é a regra permanente, que continua exigindo o sim
    explícito num desfecho próprio.
    """
    rota._pedir_tratativas(
        sessao, "outro_motivo_confirmado_pelo_cliente", "mensagem longa o bastante aqui"
    )

    acoes = [t.acao for t in tratativas.TRATATIVAS.pendentes()]
    assert tratativas.Acao.INATIVAR_ENQUANTO_NO_LOCAL in acoes
    assert tratativas.Acao.FINALIZAR_EVENTO in acoes
    assert tratativas.Acao.CRIAR_REGRA_DE_BASE not in acoes, "permanente, não: essa pede sim"


def test_a_placa_vem_da_ocorrencia_e_nunca_do_texto(sessao) -> None:
    """⚠️ O alvo vem da ocorrência, nunca do texto — e esta é a linha em que essa regra vive.

    O cliente pode escrever "inative a placa XYZ1234" o quanto quiser: a placa
    que vai é a da ocorrência que abriu esta conversa. É o único ponto do
    projeto em que uma conversa chega perto de escrever no banco da empresa.
    """
    rota._pedir_tratativas(
        sessao,
        "veiculo_em_manutencao",
        "Pode inativar a placa XYZ1234 por favor, é essa mesmo",
    )

    for t in tratativas.TRATATIVAS.pendentes():
        assert t.veiculo == "AKK9832"
        assert "XYZ1234" not in str(t.parametros)


def test_as_duas_inativacoes_sao_acoes_diferentes() -> None:
    """⚠️ Operações diferentes têm nomes diferentes.

    Uma está presa ao local, a outra ao relógio. Confundi-las desativa o alarme
    de um caminhão que está justamente se movendo — que é o evento de movimento
    sem ignição, e o pior caso possível para errar.
    """
    assert (
        tratativas.Acao.INATIVAR_ENQUANTO_NO_LOCAL is not tratativas.Acao.INATIVAR_POR_PERIODO
    )
    assert rota.TRATATIVA_POR_DESFECHO["veiculo_em_manutencao"] is (
        tratativas.Acao.INATIVAR_ENQUANTO_NO_LOCAL
    )
    assert rota.TRATATIVA_POR_DESFECHO["reboque_autorizado"] is (
        tratativas.Acao.INATIVAR_POR_PERIODO
    )


def test_todo_desfecho_do_mapa_existe_no_catalogo() -> None:
    """Mapa apontando para desfecho que não existe é ação que nunca dispara."""
    todos = {d for t in catalogo.CATALOGO for d in t.desfechos_permitidos}
    for desfecho in rota.TRATATIVA_POR_DESFECHO:
        assert desfecho in todos, f"{desfecho} não está em nenhum playbook"


# ─────────────────── o ralo do "outro motivo" fica legível ───────────────────


def test_outro_motivo_esta_na_lista_branca_da_bateria() -> None:
    assert catalogo.desfecho_permitido("REMOCAO_BATERIA", rota.DESFECHO_OUTRO_MOTIVO)


def test_fechar_sem_dizer_o_motivo_nao_conta_como_contido() -> None:
    """Desfecho genérico é ralo por natureza. A trava o mantém legível.

    Exigir o motivo em texto não impede o ralo — impede que ele seja **mudo**.
    É o que permite ler a lista depois e descobrir qual causa apareceu tantas
    vezes que merece nome próprio no catálogo.
    """
    assert rota._motivo_escrito("Certo, entendi que o mecânico mexeu no chicote hoje cedo.")
    assert not rota._motivo_escrito("Ok, encerrado!")
    assert not rota._motivo_escrito("")


# ─────────────────── o executor que ainda não executa ───────────────────


@pytest.mark.asyncio
async def test_o_executor_registra_e_nao_executa(sessao) -> None:
    """⚠️ Esta classe existe para NÃO fazer nada, e isso é o ponto.

    Ela marca onde a chamada à API vai entrar, com a assinatura que vai ter, e
    mantém o resto do código escrito contra a versão final desde já. Quando a
    TI liberar a escrita, nem a rota nem a conversa nem o painel mudam.
    """
    t = tratativas.TRATATIVAS.pedir(
        sessao.ocorrencia_id, "AKK9832", tratativas.Acao.FINALIZAR_EVENTO, resumo="x"
    )

    resultado = await tratativas.EXECUTOR.executar(t)

    assert "ainda não existe" in resultado
    assert t.pendente, "nada foi executado, então nada pode sair da fila"


def test_o_playbook_nao_repete_pergunta_ja_respondida() -> None:
    """Atendimento real, 28/08/2026.

    A IA ofereceu "quer me contar o que aconteceu?", o cliente respondeu
    **"Foi eu"**, e ela devolveu *"Foi você que desligou a chave geral, ou o
    veículo tá em manutenção?"*.

    Ele já tinha respondido. "Fui eu" é chave geral desligada pelo motorista:
    ninguém responde isso quando o veículo está numa oficina, porque quem está
    em manutenção diz que está em manutenção.

    Devolver a mesma pergunta fechada depois de a pessoa ter respondido é o que
    faz um atendimento parecer formulário, e é exatamente a sensação que este
    projeto existe para não causar.
    """
    playbook = (RAIZ_PROMPTS / "playbooks" / "PB-BATERIA.md").read_text(encoding="utf-8")

    assert "Assumiu a autoria sem dizer o quê" in playbook
    assert "Nunca repita uma pergunta que a pessoa já respondeu" in playbook
    assert "pergunte só o que falta" in playbook

    # Mas reconhecer a autoria não é concluir o método: o alarme é de remoção
    # de bateria, e isso acontece de mais de um jeito. Ver o teste abaixo.
    assert "ele confirmou **quem**, não **o quê**" in playbook


def test_o_playbook_avisa_o_cliente_do_que_a_central_vai_fazer() -> None:
    """Atendimento real, 28/08/2026. O cliente disse "não, varia".

    A IA respondeu *"já registro aqui como chave geral desligada por você,
    então o alerta encerra"* e fechou. Correto no sistema, e inútil para ele:
    acabou de desligar a chave, continua parado no mesmo lugar, e a pergunta na
    cabeça dele é se vai receber outra notificação em dez minutos.

    Responder essa pergunta é metade do atendimento. "Registrei" descreve o que
    aconteceu do nosso lado; o cliente precisa saber o que acontece do dele.
    """
    playbook = (RAIZ_PROMPTS / "playbooks" / "PB-BATERIA.md").read_text(encoding="utf-8")

    plano = " ".join(playbook.split())

    # ⚠️ Era um AVISO e virou PERGUNTA em 28/08/2026, a pedido da operação: a
    # supressão desliga o alarme de um veículo que não é nosso, e essa decisão
    # é do dono dele. Ver `test_a_ia_pergunta_antes_de_suprimir_em_todos_os_caminhos`.
    assert "PEÇA autorização para a supressão temporária" in plano
    assert "Quando ele sair de lá, os avisos voltam automaticamente" in plano
    assert "Nunca encerre só dizendo que registrou" in playbook


def test_o_playbook_nao_conclui_o_metodo_a_partir_da_autoria() -> None:
    """Observação da operação, sobre um erro que eu introduzi.

    A IA disse *"Entendi, foi você que desligou a chave geral"* depois de um
    "Fui eu". Ele confirmou **quem**, não **o quê** — e a regra que eu tinha
    escrito mandava concluir chave geral, o que é inferência a mais.

    Remoção de bateria acontece de vários jeitos: chave geral desligada,
    bateria retirada para carregar, terminal solto, alguém mexendo na parte
    elétrica. Afirmar o método faz o cliente ter de corrigir de novo, e foi
    exatamente por uma correção dessas ("é uma moto") que um atendimento
    encerrou mais cedo neste mesmo dia.

    O que a Central precisa saber é se aquilo é **rotina naquele lugar**. O
    método não muda o que ela faz.
    """
    playbook = (RAIZ_PROMPTS / "playbooks" / "PB-BATERIA.md").read_text(encoding="utf-8")

    assert "Não conclua que foi a chave geral" in playbook
    assert "foi você que desligou a bateria" in playbook
    assert "não o método" in playbook.replace("\n", " ")
