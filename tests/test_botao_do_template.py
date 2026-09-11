"""O toque em botão do modelo, e o caminho fixo do "Preciso de ajuda!".

**Falha real, 27/08/2026.** O template novo chegou com os dois botões, o
A operação tocou em "Preciso de ajuda!" e **não aconteceu nada**. O log mostrava
o `POST /whatsapp/meta` com 200, e mais nada: `_uma()` devolvia `None` para
`type: "button"` e o toque era descartado em silêncio.

Isso é pior do que não ter botão. Quem digita e não recebe resposta desconfia;
quem toca num botão escrito "Preciso de ajuda!" acredita que pediu socorro.

Os testes aqui guardam três coisas, e cada uma corresponde a uma metade do
defeito ou ao desenho que veio depois:

* o toque **chega** — nos dois formatos que a Meta usa;
* toque e digitação **não são a mesma coisa** — só o primeiro dispara roteiro;
* a ordem das três falas, que é o que faz a conversa fazer sentido.
"""

from __future__ import annotations

import pytest

from central_ia.api.rotas import whatsapp as rota
from central_ia.config import Settings
from central_ia.domain import eventos as catalogo
from central_ia.integrations.mensageria import modelos
from central_ia.integrations.mensageria.meta import extrair
from central_ia.orchestration.sessao_whatsapp import Sessao, Sessoes

TELEFONE = "+5541999999999"
DADOS = {"placa": "ABC-1234", "interlocutor": "Bruno da Silva"}


def _payload(mensagem: dict) -> dict:
    """Envelope da Meta, com os cinco níveis de aninhamento que ela usa."""
    return {"entry": [{"changes": [{"value": {"messages": [mensagem]}}]}]}


# ─────────────────────────── o toque chega ───────────────────────────


def test_resposta_rapida_de_modelo_e_lida() -> None:
    """`type: "button"` — o formato do nosso disparo.

    Este é literalmente o payload que sumiu em 27/08.
    """
    (recebida,) = extrair(
        _payload(
            {
                "from": "5541999999999",
                "id": "wamid.X",
                "type": "button",
                "button": {"payload": "Preciso de ajuda!", "text": "Preciso de ajuda!"},
            }
        )
    )

    assert recebida.botao == "Preciso de ajuda!"
    assert recebida.texto == "Preciso de ajuda!"


def test_botao_de_mensagem_interativa_e_lido() -> None:
    """`type: "interactive"` — o formato de menu enviado pela API.

    Ainda não usamos, e é justamente por isso que entra agora: o dia em que
    alguém mandar uma lista de opções, o toque não vai sumir de novo.
    """
    (recebida,) = extrair(
        _payload(
            {
                "from": "5541999999999",
                "id": "wamid.Y",
                "type": "interactive",
                "interactive": {
                    "type": "button_reply",
                    "button_reply": {"id": "ajuda", "title": "Preciso de ajuda!"},
                },
            }
        )
    )

    assert recebida.botao == "Preciso de ajuda!"


def test_texto_digitado_nao_e_botao() -> None:
    """A distinção que sustenta o caminho fixo.

    Se digitar valesse como toque, quem escrevesse "preciso de ajuda!" no meio
    de uma conversa receberia um roteiro em vez de resposta.
    """
    (recebida,) = extrair(
        _payload(
            {
                "from": "5541999999999",
                "id": "wamid.Z",
                "type": "text",
                "text": {"body": "Preciso de ajuda!"},
            }
        )
    )

    assert recebida.botao is None
    assert recebida.texto == "Preciso de ajuda!"


# ─────────────────── o rótulo do código bate com o publicado ───────────────────


def test_os_rotulos_batem_com_o_modelo_publicado() -> None:
    """O código decide caminho por estas strings; o cliente lê as do `.json`.

    Renomear o botão no modelo sem trocar a constante faria o toque virar
    mensagem comum — a IA responderia alguma coisa, o caminho fixo sumiria, e
    nada no log diria que foi isso.
    """
    from central_ia.api.rotas.eventos import TEMPLATE_ALERTA

    assert modelos.botoes(TEMPLATE_ALERTA) == [rota.BOTAO_AJUDA, rota.BOTAO_TUDO_BEM]


# ─────────────────────────── o caminho completo ───────────────────────────


@pytest.fixture
def sessao() -> Sessao:
    tipo = catalogo.por_codigo("REMOCAO_BATERIA")
    assert tipo is not None
    return Sessoes().abrir(TELEFONE, tipo, "TEXTO", DADOS)


async def _ok() -> bool:
    return True


@pytest.mark.asyncio
async def test_o_toque_vai_direto_para_a_ia(monkeypatch, sessao) -> None:
    """Uma mensagem só, e ela é da IA.

    **Havia uma frase fixa aqui, e ela foi removida em 27/08/2026.** O roteiro
    mandava responder "vou lhe transferir para um colega especialista" antes do
    turno da IA. Funcionou tecnicamente e falhou no que importa: o modelo leu
    aquilo escrito em nome dele, concluiu que o caso não era mais seu, e
    respondeu *"Ok, Ana, vou registrar aqui no sistema. Qualquer dúvida é
    só entrar em contato!"* — encerrou em vez de tratar, justamente no caso do
    cliente pedindo ajuda.

    Este teste guarda a ausência da frase, e não a presença de outra: nada pode
    sair antes do turno do modelo.
    """
    enviadas: list[str] = []
    falou: list[str] = []

    async def _responder(cfg, para, texto, em_audio=False):  # noqa: ARG001
        enviadas.append(texto)
        return True

    async def _falar(cfg, s):  # noqa: ARG001
        falou.append(s.ocorrencia_id)

    monkeypatch.setattr(rota, "_responder", _responder)
    monkeypatch.setattr(rota, "_falar", _falar)

    await rota._atender_pedido_de_ajuda(object(), sessao, rota.BOTAO_AJUDA)

    assert enviadas == [], "nada pode ser dito antes do turno da IA"
    assert falou == [sessao.ocorrencia_id]

    # E o toque é a última coisa no histórico: o modelo responde a ele.
    ultimo = sessao.historico[-1]
    assert ultimo.papel == "user"
    assert ultimo.conteudo.startswith(rota.BOTAO_AJUDA)


@pytest.mark.asyncio
async def test_a_nota_oferece_as_duas_saidas_e_proibe_encerrar(monkeypatch, sessao) -> None:
    """As duas metades do defeito de 27/08, uma em cada frase da nota."""
    monkeypatch.setattr(rota, "_falar", lambda *a, **k: _ok())

    await rota._atender_pedido_de_ajuda(object(), sessao, rota.BOTAO_AJUDA)

    nota = sessao.historico[-1].conteudo
    assert "TOCOU no botão" in nota
    assert "NÃO encerre a ocorrência neste turno" in nota
    # As duas saídas, na mesma mensagem: contar o que houve, ou ir para um
    # operador. Sem prometer telefone, que é o que não controlamos.
    assert "passe para um dos nossos operadores" in nota
    assert "NUNCA diga que alguém vai ligar" in nota


@pytest.mark.asyncio
async def test_aceitar_a_ligacao_vai_para_a_fila_mesmo_dizendo_so_sim(
    monkeypatch, sessao
) -> None:
    """⚠️ O caminho que quase não funcionou.

    A IA oferece «quer que um dos nossos operadores te ligue?». Quem aceita
    responde curto: «sim», «pode ser», «isso». **Nada disso um detector de
    pedido de atendente reconhece** e, sem a marca de que houve oferta, o
    escalonamento cairia no caminho comum, que encerra o caso em vez de mandar
    para a fila.

    A pergunta foi nossa, então a resposta curta era previsível. Quem cria o
    contexto é quem tem de lembrar dele.
    """
    monkeypatch.setattr(rota, "_falar", lambda *a, **k: _ok())

    await rota._atender_pedido_de_ajuda(object(), sessao, rota.BOTAO_AJUDA)

    assert sessao.pediu_ajuda is True, "sem esta marca o «sim» solto seria ignorado"


@pytest.mark.asyncio
async def test_a_despedida_nao_promete_telefone_nem_prazo(monkeypatch, sessao) -> None:
    """⚠️ Houve uma versão que dizia "ele vai te ligar", e ela saiu.

    **Não controlamos isso.** Quem pega o caso pode ligar, pode escrever no
    WhatsApp, pode fazer os dois. Prometer o telefone deixaria a pessoa
    esperando uma chamada que talvez venha como mensagem, e o pior de uma
    promessa dessas é que ela parece cumprida do nosso lado.

    Pelo mesmo motivo não há prazo: "em instantes" depende de uma fila que não
    é nossa.
    """
    ditas: list[str] = []

    async def _guardar(cfg, para, texto, em_audio=False):  # noqa: ARG001
        ditas.append(texto)
        return True

    monkeypatch.setattr(rota, "_responder", _guardar)

    class _Cfg:
        escalonamento_humano_ativo = False
        whatsapp_responder_em_audio = False

    sessao.pediu_ajuda = True
    await rota._entregar_a_um_humano(_Cfg(), sessao, "aceitou o operador")

    (frase,) = ditas
    assert "operadores" in frase
    for promessa in ("ligar", "ligação", "telefone", "minuto", "instante", "segundo"):
        assert promessa not in frase.lower(), f"a despedida promete «{promessa}»"


@pytest.mark.asyncio
async def test_a_nota_proibe_cumprimentar_e_renomear_o_evento(monkeypatch, sessao) -> None:
    """⛔ **As duas instruções que causaram o defeito de 10/09/2026.**

    A nota mandava *"cumprimente com «{saudacao}» e o primeiro nome dele"* e
    *"diga qual foi o evento em poucas palavras"*. O cliente tocou «Preciso de
    ajuda!» num pânico e a IA respondeu, obedecendo:

        "Bom dia, Ana. Sobre o alerta de pânico do veículo ABC1D23…"

    Bom dia duas vezes, com um toque de botão no meio — e a palavra que o
    `PB-PANICO` proíbe, impressa no celular de quem pode estar sob coação.

    As duas nasceram quando o template não cumprimentava nem nomeava o evento.
    Hoje ele faz as duas coisas, então a nota manda o oposto — e é a placa,
    não o alarme, que identifica o veículo.
    """
    monkeypatch.setattr(rota, "_falar", lambda *a, **k: _ok())

    await rota._atender_pedido_de_ajuda(object(), sessao, rota.BOTAO_AJUDA)

    nota = sessao.historico[-1].conteudo
    assert "NÃO cumprimente" in nota
    assert "não repita o nome do evento" in nota
    # A frase pronta que ela deve copiar.
    assert "Estamos à disposição" in nota

    # ⛔ E ela não pode recomeçar como a notificação recomeça. O template do
    # pânico abre com «Estamos acompanhando a viagem do veículo ABC1D23»; a
    # primeira frase da nota dizia «Estamos acompanhando o veículo {placa}», e
    # as duas mensagens saíam com as mesmas quatro palavras iniciais.
    assert "Estamos acompanhando o veículo" not in nota


@pytest.mark.asyncio
async def test_a_nota_nao_deixa_o_toque_virar_escalonamento(monkeypatch, sessao) -> None:
    """⛔ **A regressão de 10/09/2026, e ela foi de redação.**

    O cliente tocou «Preciso de ajuda!» e a IA respondeu *"Claro, Pedro! Já
    estou passando o seu atendimento para um dos nossos operadores"*. Escalou
    sem perguntar nada, usando a frase que só vale DEPOIS de o cliente aceitar.

    Três causas, e este teste tranca as três:

    1. a instrução principal estava enterrada depois de três «NÃO». O que fazer
       tem de aparecer antes do que não fazer;
    2. «o botão diz que ele quer ajuda» somado a «se ele aceitar o operador»
       deixava o toque parecer o aceite;
    3. a nota proibia encerrar, mas não escalar. São coisas diferentes, e foi
       por essa fresta que passou.
    """
    monkeypatch.setattr(rota, "_falar", lambda *a, **k: _ok())

    await rota._atender_pedido_de_ajuda(object(), sessao, rota.BOTAO_AJUDA)

    nota = sessao.historico[-1].conteudo
    assert "NÃO É ACEITAR" in nota, "o toque não pode parecer aceite do operador"
    assert "NÃO escale neste turno" in nota
    assert "NÃO use a marca de escalonamento neste turno" in nota

    # A ação vem antes das proibições: enterrada, ela perde para elas.
    assert nota.index("Estamos à disposição") < nota.index("NÃO escale")

    # E o ramo do aceite fica visivelmente no turno SEGUINTE.
    assert nota.index("SÓ NA RESPOSTA SEGUINTE") < nota.index("vou passar para um operador")


@pytest.mark.asyncio
async def test_o_operador_ve_so_o_rotulo(monkeypatch, sessao) -> None:
    """A nota é andaime. Na tela do operador ela seria ruído e confusão."""
    monkeypatch.setattr(rota, "_falar", lambda *a, **k: _ok())

    await rota._atender_pedido_de_ajuda(object(), sessao, rota.BOTAO_AJUDA)

    do_painel = sessao.falas[-1]
    assert do_painel.quem == "cliente"
    assert do_painel.texto == rota.BOTAO_AJUDA
    assert "[" not in do_painel.texto


@pytest.mark.asyncio
async def test_o_toque_nao_gasta_turno_da_ia(monkeypatch, sessao) -> None:
    """Quem tocou foi o cliente. O turno é o que a IA responde, e vem depois."""
    monkeypatch.setattr(rota, "_falar", lambda *a, **k: _ok())

    await rota._atender_pedido_de_ajuda(object(), sessao, rota.BOTAO_AJUDA)

    assert sessao.turnos_ia == 0
    assert sessao.custo_usd == 0.0


@pytest.mark.asyncio
async def test_tocar_no_botao_conta_como_resposta(monkeypatch, sessao) -> None:
    """Um toque é contato. Sem isto o caso viraria "não contactado" no painel."""
    monkeypatch.setattr(rota, "_falar", lambda *a, **k: _ok())

    assert sessao.houve_resposta is False
    await rota._atender_pedido_de_ajuda(object(), sessao, rota.BOTAO_AJUDA)

    assert sessao.houve_resposta is True


@pytest.mark.asyncio
async def test_nao_saem_duas_despedidas_quando_a_ia_escala(monkeypatch, sessao) -> None:
    """⚠️ O cliente recebeu dois tchaus seguidos, 28/08/2026.

        "Ok, Bruno, vou registrar aqui no sistema."
        "Claro, Bruno! Já estou passando o seu atendimento..."

    Quando a IA escala pela marca de controle, ela **já escreveu a despedida** e
    ela já saiu no celular. Mandar a nossa em cima é uma segunda mensagem de
    tchau, e ninguém escreve assim.

    A frase existe para o outro caminho: o pedido explícito de atendente,
    detectado antes de o modelo ser chamado, onde ninguém falou nada ainda.
    """
    ditas: list[str] = []

    async def _guardar(cfg, para, texto, em_audio=False):  # noqa: ARG001
        ditas.append(texto)
        return True

    monkeypatch.setattr(rota, "_responder", _guardar)

    class _Cfg:
        escalonamento_humano_ativo = False
        whatsapp_responder_em_audio = False

    await rota._entregar_a_um_humano(
        _Cfg(), sessao, "a IA escalou", ja_se_despediu=True
    )

    assert ditas == [], "a IA já tinha se despedido; a nossa frase iria em cima"
    # E o caso vai para a fila do mesmo jeito: o que muda é só a mensagem.
    assert sessao.escalada is True


@pytest.mark.asyncio
async def test_a_nota_prescreve_a_frase_de_quem_aceitou_o_operador(
    monkeypatch, sessao
) -> None:
    """⚠️ A IA disse a frase errada, 28/08/2026.

    O cliente aceitou o operador, o painel encaminhou certo, e ele recebeu
    *"Ok, Bruno, vou registrar aqui no sistema. Qualquer dúvida é só entrar
    em contato!"*.

    Essa é a despedida de quando **não há operador**, e ela vem do contexto
    porque `ESCALONAMENTO_HUMANO_ATIVO` está `false`. Só que este caminho
    escala mesmo assim, de propósito: a mensagem contradizia o que de fato
    aconteceu, e o cliente ficou sem saber que alguém vai retomar.

    A frase agora vem prescrita na nota, **com o nome real já dentro** e não um
    marcador: o modelo copia melhor uma frase pronta do que uma com lacuna.
    """
    monkeypatch.setattr(rota, "_falar", lambda *a, **k: _ok())

    await rota._atender_pedido_de_ajuda(object(), sessao, rota.BOTAO_AJUDA)

    nota = sessao.historico[-1].conteudo
    assert "vou passar para um operador te atender agora" in nota
    assert "Bruno" in nota, "o nome real precisa estar na frase, não um marcador"
    assert "não a despedida" in nota


def test_a_despedida_do_operador_nao_agradece_paciencia() -> None:
    """Leitura da operação no celular, 28/08/2026.

    A frase terminava em *"Obrigado pela paciência, viu? Qualquer coisa, a Bahrd
    está à disposição."* e saiu por três motivos, do menor para o maior:

    1. "viu?" é vício de fala, alonga sem dizer nada.
    2. "Obrigado" está no masculino, e a persona é feminina.
    3. **Ninguém teve paciência.** A pessoa pediu um operador e está sendo
       passada no mesmo turno. Agradecer paciência sugere espera, e sugerir
       espera para quem não esperou é começar a passagem pedindo desculpa por
       algo que não aconteceu.

    O que a frase precisa dizer continua inteiro: que foi entendido, o que vai
    acontecer, e que ninguém está sendo largado.
    """
    frase = rota.DESPEDIDA_PARA_HUMANO

    assert "viu?" not in frase
    assert "paciência" not in frase
    assert "Obrigado" not in frase, "a persona é feminina"
    assert "passando o seu atendimento" in frase
    assert "continua com você daqui" in frase


def test_a_despedida_de_escalonamento_nao_finge_caso_resolvido() -> None:
    """Seis roteiros de 28/08 terminaram na mesma frase errada.

        Cliente: não desliguei nada não
        IA:      Ok, Bruno, vou registrar aqui no sistema. Qualquer dúvida
                 é só entrar em contato!

    Negar a causa de uma remoção de bateria é, na Central, sinal de roubo. A
    decisão de escalar estava certa; a frase é que soava como se nada tivesse
    acontecido, porque "registrar" é o que se diz de um caso que acabou.

    A mesma frase saiu para quem mandou a IA parar de encher, para quem pediu
    boleto e para quem quis cancelar contrato. E em dois desses o modelo ainda
    escreveu uma despedida própria e emendou esta, deixando o cliente com duas
    versões contraditórias do que ia acontecer.
    """
    from central_ia.agent import atendimento_real

    sem_operador = atendimento_real.DESPEDIDA_SEM_OPERADOR
    com_operador = atendimento_real.DESPEDIDA_COM_OPERADOR

    assert "vou registrar aqui no sistema" not in sem_operador
    assert "para a Central acompanhar" in sem_operador

    # E nenhuma das duas promete prazo: a conversa não controla quando alguém
    # pega o caso.
    for frase in (sem_operador, com_operador):
        assert "só um instante" not in frase
        assert "instante" not in frase
        assert "minuto" not in frase
        assert "ligar" not in frase

    # A instrução tem de proibir a emenda, senão o modelo escreve a dele antes.
    instrucao = atendimento_real.INSTRUCAO_DE_TURNO
    assert "A mensagem inteira deste turno é" in instrucao
    assert "Nada antes dela, nada depois" in instrucao

@pytest.fixture
def sessao_de_panico() -> Sessao:
    tipo = catalogo.por_codigo("PANICO")
    assert tipo is not None
    return Sessoes().abrir(TELEFONE, tipo, "TEXTO", DADOS)


@pytest.mark.asyncio
async def test_no_panico_o_toque_vai_direto_para_um_humano(monkeypatch, sessao_de_panico) -> None:
    """⛔ **No pânico, o toque JÁ É o pedido de gente.** Decisão de 10/09/2026.

    Nos outros eventos a IA pergunta antes: *"quer me contar o que houve ou
    prefere que eu passe para um operador?"*. É a pergunta certa quando o pior
    caso é uma bateria removida no pátio.

    No pânico não é. Quem toca em «Preciso de ajuda!» num alarme de emergência
    já respondeu a pergunta, e devolvê-la custa um turno inteiro de espera
    justamente no evento em que o tempo é o mais caro. Pior: a resposta pode
    nunca vir, porque quem está sob coação não digita.
    """
    falou = False

    async def _nao_deveria_falar(*_a: object, **_k: object) -> bool:
        nonlocal falou
        falou = True
        return True

    monkeypatch.setattr(rota, "_falar", _nao_deveria_falar)
    monkeypatch.setattr(rota, "_dizer", lambda *a, **k: _ok())

    await rota._atender_pedido_de_ajuda(Settings(), sessao_de_panico, rota.BOTAO_AJUDA)

    assert sessao_de_panico.escalada is True
    assert falou is False, "o pânico não gasta um turno de IA perguntando"


@pytest.mark.asyncio
async def test_no_panico_a_nota_da_pergunta_nao_entra_no_historico(
    monkeypatch, sessao_de_panico
) -> None:
    """A nota manda oferecer as duas saídas. Aqui não há duas saídas."""
    monkeypatch.setattr(rota, "_falar", lambda *a, **k: _ok())
    monkeypatch.setattr(rota, "_dizer", lambda *a, **k: _ok())

    await rota._atender_pedido_de_ajuda(Settings(), sessao_de_panico, rota.BOTAO_AJUDA)

    historico = " ".join(t.conteudo for t in sessao_de_panico.historico)
    assert "Estamos à disposição" not in historico


@pytest.mark.asyncio
async def test_nos_outros_eventos_a_pergunta_continua(monkeypatch, sessao) -> None:
    """⚠️ A trava do outro lado: o atalho do pânico não pode vazar para os demais.

    Numa remoção de bateria, escalar direto tiraria do cliente a chance de
    resolver por ali — que é justamente a contenção que este sistema existe
    para medir.
    """
    monkeypatch.setattr(rota, "_falar", lambda *a, **k: _ok())

    await rota._atender_pedido_de_ajuda(object(), sessao, rota.BOTAO_AJUDA)

    assert sessao.escalada is False
    assert "Estamos à disposição" in sessao.historico[-1].conteudo
