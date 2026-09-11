"""A IA não pode prometer o que o sistema não faz.

Dois defeitos achados na rodada de roteiros de 28/08/2026, com a mesma forma: a
conversa terminou bonita e **nada aconteceu do outro lado**. É o pior tipo de
erro num sistema que a Central vai usar sem ficar olhando, porque ninguém
percebe até o cliente reclamar.
"""

from __future__ import annotations

from central_ia.agent.prompts import RAIZ_PROMPTS
from central_ia.api.rotas import whatsapp as rota
from central_ia.domain import eventos as catalogo
from central_ia.orchestration import tratativas


def test_a_base_autorizada_pede_a_regra() -> None:
    """Roteiro D3: prometeu regra permanente e não pediu nada.

        Cliente: tô na base
        IA:      Entendi, então esse endereço é a base de vocês. Quer que a
                 gente deixe de avisar quando isso acontecer aí?
        Cliente: pode deixar de avisar aqui sim
        IA:      Combinado, vou registrar como base de vocês, sem avisos por
                 aqui daqui pra frente.

    Fechou com `local_e_base_do_cliente`, que não está no mapa de tratativas.
    Nenhum pedido saiu, e o cliente receberia o mesmo alerta na noite seguinte.

    O conserto é o mesmo que a chave geral recebeu de manhã, no mesmo dia: um
    desfecho separado que **carrega a autorização**. Regra que vale para sempre
    não pode depender de o modelo ter contado direito o que combinou.
    """
    assert catalogo.desfecho_permitido("REMOCAO_BATERIA", "base_com_regra_autorizada")

    acao = rota.TRATATIVA_POR_DESFECHO.get("base_com_regra_autorizada")
    assert acao is tratativas.Acao.CRIAR_REGRA_DE_BASE

    # E o desfecho sem autorização continua sem gerar regra nenhuma: quem
    # preferiu continuar sendo avisado não pode acabar em silêncio.
    assert "local_e_base_do_cliente" not in rota.TRATATIVA_POR_DESFECHO


def test_o_playbook_separa_os_dois_desfechos_de_base() -> None:
    """A distinção precisa estar escrita onde o modelo lê."""
    playbook = (RAIZ_PROMPTS / "playbooks" / "PB-BATERIA.md").read_text(encoding="utf-8")
    plano = playbook.replace("\n", " ")

    assert "`base_com_regra_autorizada`" in playbook
    assert "Só com o sim explícito" in playbook
    assert "prefere continuar recebendo" in plano
    assert "`local_e_base_do_cliente`. Fecha o caso e não mexe em mais nada" in plano


def test_o_playbook_do_reboque_nao_manda_falar_com_o_gestor() -> None:
    """Roteiro L1: *"Vou confirmar isso com o gestor de frota, só um momento."*

    A IA não fala com o gestor de frota. Não tem o telefone, não tem ferramenta,
    não existe ninguém esperando contato dela. O passo 4 mandava *"ligue ou
    mande mensagem"*, e ela obedeceu do único jeito que conseguia: **inventando
    que ia obedecer.**

    É a mesma família do `consultar_posicao_veiculo` e do `validar_credencial`,
    tirados em 27/08, e sobreviveu à limpeza por estar escrita como ação em
    português e não como nome de função. Por isso este teste procura o
    comportamento, não o identificador.
    """
    playbook = (RAIZ_PROMPTS / "playbooks" / "PB-MOV-SEM-IGNICAO.md").read_text(encoding="utf-8")
    plano = playbook.replace("\n", " ")

    assert "Você não fala com o gestor de frota" in plano
    assert "Quem procura o gestor é o operador humano" in plano
    assert "Nunca diga «vou confirmar com o gestor»" in plano
    assert "só um\nmomento»" in playbook or "só um momento»" in plano

    # E a instrução que produzia a promessa não pode voltar.
    assert "Ligue ou mande mensagem" not in plano
    assert "vá direto ao gestor de frota" not in plano


def test_nenhum_playbook_manda_a_ia_procurar_alguem() -> None:
    """A regra geral, para não caçar caso a caso.

    A IA tem exatamente um canal: a conversa aberta. Qualquer instrução que
    mande **ela** ligar, telefonar ou procurar outra pessoa é uma promessa que
    o sistema não cumpre, e o modelo repassa essa promessa ao cliente.

    As menções que sobram descrevem o que o **operador** faz, ou o que a
    ocorrência já traz do catálogo, e por isso a busca é pelo imperativo.
    """
    import re

    proibidas = re.compile(
        r"^\s*(?:[-*]\s*)?(?:\*\*)?(?:Ligue|Telefone|Procure|Entre em contato)\b",
        re.IGNORECASE | re.MULTILINE,
    )

    achados = [
        f"{caminho.name}: {linha.strip()[:70]}"
        for caminho in (RAIZ_PROMPTS / "playbooks").glob("*.md")
        for linha in caminho.read_text(encoding="utf-8").splitlines()
        if proibidas.match(linha)
    ]

    assert not achados, "playbook manda a IA procurar alguém:\n  " + "\n  ".join(achados)


def test_a_recusa_da_supressao_tem_desfecho_proprio() -> None:
    """Roteiro A3, na segunda rodada: suprimiu o que o cliente pediu para manter.

        Cliente: não, prefiro continuar recebendo os avisos
        IA:      Combinado, Bruno. Registrado como manutenção, tá tudo certo.
        >> tratativa: inativar_enquanto_no_local

    O primeiro conserto do dia tirou a quebra técnica deste turno e revelou o
    que estava embaixo dela. Sem um desfecho para a recusa, a IA fechou com
    `veiculo_em_manutencao`, e o mapa de tratativas pediu **a supressão que ele
    acabara de recusar**.

    É o terceiro par do mesmo desenho, e agora os três estão fechados: a
    autorização mora no nome do desfecho, e a ausência dela também.
    """
    assert catalogo.desfecho_permitido("REMOCAO_BATERIA", "veiculo_em_manutencao_com_avisos")
    assert "veiculo_em_manutencao_com_avisos" not in rota.TRATATIVA_POR_DESFECHO

    playbook = (RAIZ_PROMPTS / "playbooks" / "PB-BATERIA.md").read_text(encoding="utf-8")
    plano = playbook.replace("\n", " ")

    assert "Se ele recusar, encerre com `veiculo_em_manutencao_com_avisos`" in plano
    assert "os avisos continuam chegando normalmente então" in plano
    assert "Nunca feche uma recusa como `veiculo_em_manutencao`" in plano


def test_os_tres_pares_de_autorizacao_seguem_a_mesma_regra() -> None:
    """A regra que os três compartilham, escrita uma vez.

    Chave geral, base do cliente e manutenção: em todos, uma escolha do cliente
    decide se a Central mexe no alarme dele. Em todos, **o desfecho carrega a
    autorização**, porque escrita permanente não pode depender de o modelo ter
    narrado direito o que combinou.

    Se algum dia alguém acrescentar um quarto par e esquecer o mapa, é aqui que
    aparece.
    """
    com_acao = {
        "chave_geral_com_regra_autorizada": tratativas.Acao.CRIAR_REGRA_DE_BASE,
        "base_com_regra_autorizada": tratativas.Acao.CRIAR_REGRA_DE_BASE,
        "veiculo_em_manutencao": tratativas.Acao.INATIVAR_ENQUANTO_NO_LOCAL,
        "chave_geral_desligada_pelo_motorista": tratativas.Acao.INATIVAR_ENQUANTO_NO_LOCAL,
        # A causa é outra, a situação do veículo é a mesma: parado no lugar,
        # com a bateria mexida. Ver `test_outro_motivo_tambem_suprime_no_local`.
        "outro_motivo_confirmado_pelo_cliente": tratativas.Acao.INATIVAR_ENQUANTO_NO_LOCAL,
    }
    # ⚠️ Estes dois ficam de fora por um motivo só, e é o mesmo: **o cliente
    # disse que prefere continuar sendo avisado.** Quem recusou não pode acabar
    # em silêncio.
    sem_acao = (
        "local_e_base_do_cliente",
        "veiculo_em_manutencao_com_avisos",
        "chave_geral_com_avisos_mantidos",
        "outro_motivo_com_avisos_mantidos",
    )

    for desfecho, acao in com_acao.items():
        assert catalogo.desfecho_permitido("REMOCAO_BATERIA", desfecho), desfecho
        assert rota.TRATATIVA_POR_DESFECHO.get(desfecho) is acao, desfecho

    for desfecho in sem_acao:
        assert catalogo.desfecho_permitido("REMOCAO_BATERIA", desfecho), desfecho
        assert desfecho not in rota.TRATATIVA_POR_DESFECHO, desfecho


def test_o_raciocinio_da_ia_nao_vai_para_o_cliente() -> None:
    """Roteiro A4: *"Boa tarde... já cumprimentei. Bruno, você costuma..."*

    A dúvida dela sobre cumprimentar foi para o celular do cliente. A instrução
    já dizia "escreva APENAS a sua próxima mensagem", e isso cobria narrar ações
    ("*consultando o sistema*"), não deliberar em voz alta sobre a própria fala.

    São coisas diferentes e a segunda é pior: narrar uma ação parece um robô
    mal-acabado; deliberar mostra a máquina por dentro para quem só queria saber
    do caminhão.
    """
    from central_ia.agent import atendimento_real

    instrucao = atendimento_real.INSTRUCAO_DE_TURNO

    assert "O que você pensa NÃO entra na mensagem" in instrucao
    assert "nunca escreva a dúvida" in instrucao
    assert "já cumprimentei" in instrucao, "o exemplo real ensina mais que a regra"


def test_a_persona_manda_usar_a_palavra_do_cliente_sem_traduzir() -> None:
    """Roteiro F4: o cliente escreveu "busão" e a IA respondeu "ônibus".

    A regra de usar a palavra dele já existia, e o modelo a cumpriu pela metade:
    trocou "veículo" pelo termo dela, mas normalizou a gíria. É a mesma falta de
    escuta, só mais disfarçada.
    """
    persona = (RAIZ_PROMPTS / "persona_core.md").read_text(encoding="utf-8")

    assert "A palavra dela, e não a versão correta dela" in persona
    assert '"busão", não "ônibus"' in persona


def test_a_persona_proibe_cumprimento_como_despedida() -> None:
    """Dois acabamentos que apareceram em quatro roteiros da rodada.

    Encerrar com «já deixei registrado. Boa tarde, Bruno!» é cumprimentar na
    saída. E cumprimentar no terceiro turno, depois de a pessoa já ter tocado
    dois botões, soa como alguém que acabou de chegar e não leu o que veio
    antes.
    """
    persona = (RAIZ_PROMPTS / "persona_core.md").read_text(encoding="utf-8")

    assert "Cumprimente só quando a sua mensagem for a primeira coisa" in persona
    assert "são chegada, nunca despedida" in persona

    # ⚠️ **A primeira versão desta regra estava errada, e o teste passava.**
    #
    # Ela dizia "cumprimente uma vez só, na sua primeira mensagem escrita". No
    # caminho dos botões a primeira mensagem escrita pelo modelo é a TERCEIRA
    # da conversa, depois da notificação e da pergunta com botões, e ele
    # obedeceu ao pé da letra: «Boa tarde, Bruno!» para quem já tinha lido
    # "Que bom, Bruno! Só preciso saber o motivo" e tocado um botão.
    #
    # A correção seguinte errou para o outro lado: proibiu cumprimentar depois
    # da notificação também. Isso é diferente, e é bom como está — quem responde
    # a um alerta automático não estranha ser cumprimentado pela pessoa que
    # aparece depois. **O que soa mal é o segundo cumprimento, não o primeiro.**
    from central_ia.agent import atendimento_real

    instrucao = " ".join(atendimento_real.INSTRUCAO_DE_TURNO.split())
    assert "Cumprimente **uma vez só**, e só se ainda não tiver falado com ela" in instrucao
    assert "A pergunta com botões conta como fala sua" in instrucao
    assert "A notificação automática do evento não conta" in instrucao
    assert "A única exceção é ela cumprimentar você primeiro" in instrucao
    assert "saudação **nunca fecha** mensagem" in instrucao
    # E a regra antiga, que mandava cumprimentar na primeira mensagem escrita,
    # não pode valer sozinha: ela é o que produziu o defeito.
    assert "A pergunta com botões, essa conta como sua fala" in instrucao

    # E a regra vive junto da EVIDÊNCIA, não só no prompt distante: é a própria
    # fala registrada que avisa ao modelo que ela já é dele.
    from central_ia.domain import eventos as catalogo_eventos
    from central_ia.integrations.mensageria import modelos
    from central_ia.orchestration.sessao_whatsapp import Sessoes

    turno = modelos.como_turno("evento_alerta", ["Remoção de bateria", "AKK9832", "17:27", "-"])
    assert turno is not None
    assert "não cumprimente" not in turno, "a notificação é voz do sistema, não dela"

    sessao = Sessoes().abrir(
        "+5541999998888", catalogo_eventos.por_codigo("REMOCAO_BATERIA"), "TEXTO", {}
    )
    sessao.registrar_frase_com_botoes("Que bom, Bruno!", ["Em manutenção"])
    marca = sessao.historico[-1].conteudo
    assert "Esta fala é SUA" in marca
    assert "não cumprimente de novo" in marca

    # A regra antiga não pode voltar: ela autoriza exatamente o que saiu errado.
    assert "na sua primeira mensagem escrita" not in instrucao
    assert "na sua primeira mensagem escrita" not in persona


def test_a_trilha_mostra_o_que_o_cliente_escreveu() -> None:
    """Roteiro B1: a trilha dizia «quero falar com uma pesoa».

    O cliente escreveu "pessoa". Quem comeu a letra foi o detector, que colapsa
    repetições para reconhecer "pessooa" e "aleeew". Mandar esse texto para a
    tela do operador é registrar, sobre uma pessoa real, um erro que ela não
    cometeu.
    """
    import inspect

    fonte = inspect.getsource(rota._entregar_a_um_humano)

    assert "ele escreveu" in fonte
    assert "sem_html(fala)" in fonte, "texto de cliente não entra cru numa tela HTML"
    assert "LIMITE_DA_FALA_NA_TRILHA" in fonte

    chamada = inspect.getsource(rota._continuar)
    assert "fala=corpo" in chamada, "sem isso a trilha volta a mostrar o normalizado"


def test_o_playbook_nao_manda_conferir_o_lugar() -> None:
    """Roteiro D8, e a razão pela qual ele não era desobediência.

        Cliente: ele tá aqui na minha garagem em Maringá
        IA:      Entendi, então essa é a base ou o pátio de vocês em Maringá?

    O evento nasceu em Curitiba e o playbook mandava comparar. Só que **a IA
    nunca recebe o local do evento em texto**: o payload da Bahrd vem sem
    `endereco` (doc 08 §5) e o template escreve "veja o mapa acima". A regra
    era letra morta.

    A saída não foi dar a coordenada ao modelo. Pedir a ele que conclua
    "-25.44, -49.26 é Curitiba, não Maringá" é pedir geografia de cabeça, e o
    jeito de errar é o caro: falso positivo vira escalonamento de cliente
    honesto, que é justamente o custo que esta POC existe para reduzir. O
    falso negativo apenas fecha o caso como já fechava.

    O sinal não se perdeu, mudou de dono: o painel mostra o ponto no mapa e a
    conversa inteira para o operador, que tem como cruzar os dois.

    Quando a Bahrd mandar o `endereco`, a regra volta comparando **nome com
    nome**, e sem código novo: `dados["posição"]` já é levado ao contexto.
    """
    playbook = (RAIZ_PROMPTS / "playbooks" / "PB-BATERIA.md").read_text(encoding="utf-8")
    plano = playbook.replace("\n", " ")

    assert "Não tente conferir o lugar" in plano
    assert "aceite como informação" in plano
    assert "Quem cruza isso com o mapa é o operador" in plano

    # A instrução que virava letra morta não pode voltar.
    assert "contradiz o local do contexto" not in plano
    assert "A telemetria não combina com o relato" not in plano

    # E a contradição que ela CONSEGUE ver continua valendo.
    assert "`inconsistencia_telemetria`" in playbook
    assert "o tipo do evento, o horário" in plano


def test_a_saudacao_nunca_fecha_a_mensagem() -> None:
    """A regra que o prompt pede três vezes e o modelo cumpre metade das vezes.

    Está na persona, está na instrução de turno, e mesmo assim saiu *"Perfeito,
    já deixei configurado assim. Boa tarde, Bruno!"* no fecho de um
    atendimento. "Bom dia" é cumprimento de chegada; no fim soa como quem
    estava indo embora e lembrou de falar.

    É o tipo de regra que não se discute com o modelo: absoluta, cosmética e
    trivial de detectar. Instrução é pedido, isto é garantia, exatamente como o
    travessão.
    """
    from central_ia.agent.escrita import sem_saudacao_no_fim

    assert (
        sem_saudacao_no_fim("Perfeito, já deixei configurado assim. Boa tarde, Bruno!")
        == "Perfeito, já deixei configurado assim."
    )
    assert (
        sem_saudacao_no_fim("Combinado, Bruno, já deixei cadastrado. Boa noite!")
        == "Combinado, Bruno, já deixei cadastrado."
    )

    # ⚠️ Cumprimento sozinho é resposta a um cumprimento dela, e sai inteiro.
    assert sem_saudacao_no_fim("Boa tarde!") == "Boa tarde!"

    # ⚠️ Na abertura ele é o certo, e não pode ser tocado.
    abertura = "Boa tarde, Bruno! Você desligou a chave geral do veículo?"
    assert sem_saudacao_no_fim(abertura) == abertura

    # E mensagem sem saudação nenhuma volta idêntica, pontuação inclusive: a
    # função não é dona da escrita, só tira o que não devia estar ali.
    assert sem_saudacao_no_fim("Tudo certo por aqui") == "Tudo certo por aqui"

    # A limpeza roda no turno, e não só na entrega, para o painel mostrar ao
    # operador o mesmo texto que chegou ao celular.
    import inspect

    from central_ia.agent import atendimento_real

    assert "sem_saudacao_no_fim(mensagem)" in inspect.getsource(atendimento_real.proximo_turno)


def test_outro_motivo_tambem_suprime_no_local() -> None:
    """Atendimento real de 28/08/2026, no ramo «Outro motivo».

        Cliente: Tive que tirar a bateria porque o suporte dela enferrujou e
                 agora precisamos soldar outro
        IA:      Entendi, Bruno, valeu por avisar! Vou registrar aqui que a
                 bateria foi retirada porque o suporte enferrujou e vocês
                 precisam soldar outro. Já tá certo aqui.

    Registrou o motivo certinho e encerrou. **O veículo continuou parado no
    mesmo lugar, com a bateria fora**, e o alarme ia disparar de novo em
    minutos: o cliente que achou ter resolvido receberia outra notificação.

    Os outros três ramos já tratavam disso, cada um do seu jeito. O ralo
    genérico existe para acolher causa que o catálogo não previu, não para
    atender pior quem cai nele.

    A supressão por local é segura aqui justamente porque **se desfaz sozinha**:
    ela termina quando o veículo se move. Não é regra permanente, e por isso não
    precisa da autorização explícita que a regra de base exige.
    """
    acao = rota.TRATATIVA_POR_DESFECHO.get("outro_motivo_confirmado_pelo_cliente")
    assert acao is tratativas.Acao.INATIVAR_ENQUANTO_NO_LOCAL

    playbook = (RAIZ_PROMPTS / "playbooks" / "PB-BATERIA.md").read_text(encoding="utf-8")
    plano = playbook.replace("\n", " ")

    # ⚠️ A regra vive no PLAYBOOK, não na nota do botão: em 28/08 um cliente
    # chegou em manutenção conversando, a nota nunca se aplicou, e a IA encerrou
    # sem fazer nada do que devia. Vale para este ramo também.
    assert "**4c. Se for OUTRO MOTIVO" in playbook
    assert "Quando ele sair de lá, os avisos voltam automaticamente" in plano
    assert "Você continua tendo de escrever qual foi o motivo" in plano

    # E a nota do botão aponta para lá, em vez de repetir a regra.
    assert "siga o passo 4c do seu playbook" in rota.NOTA_POR_CAUSA[rota.BOTAO_OUTRO_MOTIVO]


def test_a_ia_pergunta_antes_de_suprimir_em_todos_os_caminhos() -> None:
    """Regra combinada com a operação, lendo um atendimento real.

        Cliente: Não varia bastante
        IA:      Entendi. Vou deixar os avisos desse veículo desconsiderados
                 enquanto ele estiver parado nesse local, e quando ele sair de
                 lá os avisos voltam automaticamente.

    O desfecho estava certo e a conduta não: ela **informou** em vez de
    perguntar. Desligar o alarme de um veículo é decisão do dono dele, e o
    playbook tinha dois pesos — a manutenção pedia autorização, a chave geral e
    o ramo genérico apenas avisavam.

    Agora os quatro caminhos perguntam: manutenção, chave geral, base do
    cliente e outro motivo.

    **E a pergunta não pode ser teatro.** Sem um desfecho para o "não", a recusa
    não teria onde ser registrada e o caso fecharia suprimindo assim mesmo. Por
    isso cada ramo ganhou o seu par.
    """
    playbook = (RAIZ_PROMPTS / "playbooks" / "PB-BATERIA.md").read_text(encoding="utf-8")
    plano = playbook.replace("\n", " ")

    # A frase é uma PERGUNTA nos quatro ramos, e nunca um aviso.
    assert "PEÇA autorização para a supressão temporária" in plano, "chave geral"
    assert "antes de encerrar, PEÇA autorização" in plano, "outro motivo"
    assert "posso deixar os avisos desse veículo desconsiderados enquanto ele" in plano
    assert "avisar quando acontecer aí, ou prefere continuar sendo notificado" in plano, "base"

    # E o aviso sem pergunta não pode voltar em nenhum deles.
    assert "diga o que a Central vai fazer agora" not in plano
    assert "«vou deixar os avisos desse veículo desconsiderados" not in plano

    # Cada "não" tem onde ser registrado.
    for recusa in (
        "veiculo_em_manutencao_com_avisos",
        "chave_geral_com_avisos_mantidos",
        "outro_motivo_com_avisos_mantidos",
        "local_e_base_do_cliente",
    ):
        assert catalogo.desfecho_permitido("REMOCAO_BATERIA", recusa), recusa
        assert recusa not in rota.TRATATIVA_POR_DESFECHO, recusa
        assert f"`{recusa}`" in playbook, recusa


def test_o_cumprimento_repetido_e_cortado_no_codigo() -> None:
    """A regra estava em três lugares do prompt e saía mesmo assim.

        IA:      Que bom, Bruno! Só preciso saber o motivo...
        Cliente: (tocou) Desliguei a chave
        IA:      Boa noite, Bruno! Isso costuma acontecer sempre nesse mesmo
                 lugar e horário?

    Ela já tinha chamado o cliente pelo nome duas mensagens antes. Instrução de
    prompt é pedido; aqui virou garantia, como o travessão e a saudação no fim.

    **Mas esta garantia é condicional**, e é o que a separa das outras duas: a
    saudação de abertura é o comportamento certo na primeira fala dela. Por isso
    a decisão mora na rota, que sabe o que já foi dito, e não no `escrita.py`.
    """
    from central_ia.agent.escrita import sem_saudacao_no_inicio
    from central_ia.domain import eventos as catalogo_eventos
    from central_ia.orchestration.sessao_whatsapp import Sessoes

    assert (
        sem_saudacao_no_inicio("Boa noite, Bruno! Isso costuma acontecer sempre?")
        == "Isso costuma acontecer sempre?"
    )
    assert sem_saudacao_no_inicio("Entendi, foi você então.") == "Entendi, foi você então."

    tipo = catalogo_eventos.por_codigo("REMOCAO_BATERIA")
    sessao = Sessoes().abrir("+5541999998888", tipo, "TEXTO", {"interlocutor": "Bruno"})

    # Só a notificação: ela ainda não falou, e o cumprimento é o certo.
    sessao.registrar_template("[notificação]", "A Bahrd Monitoramento informa...")
    assert not rota._ja_falou_com_ele(sessao)
    assert rota._sem_cumprimento_repetido(sessao, "Boa noite, Bruno! Foi você?").startswith(
        "Boa noite"
    )

    # Depois da pergunta com botões, não é mais.
    sessao.registrar_frase_com_botoes("Que bom, Bruno!", ["Em manutenção"])
    sessao.registrar_cliente("Desliguei a chave")
    assert rota._ja_falou_com_ele(sessao)
    assert rota._sem_cumprimento_repetido(sessao, "Boa noite, Bruno! Foi você?") == "Foi você?"

    # ⚠️ A exceção que não se abre mão: se ele cumprimenta, ela devolve.
    sessao.registrar_cliente("boa noite, aqui é o Bruno")
    assert rota._sem_cumprimento_repetido(sessao, "Boa noite! Foi você?") == "Boa noite! Foi você?"


def test_a_ia_diz_o_nome_inteiro_da_empresa() -> None:
    """Leitura da operação, num atendimento real.

        IA: Bom dia, Bruno! Aqui é a assistente virtual da Bahrd. A bateria do
            veículo AKK9832 foi desligada.

    A notificação que a pessoa acabou de ler diz **"A Bahrd Monitoramento
    informa"**, e a mensagem seguinte encolhe o nome. "Bahrd" sozinho é como se
    fala aqui dentro; para o cliente é o nome da empresa que ele contratou.

    A checagem é sobre o que a IA **diz**: linhas de citação nos prompts, frases
    prescritas entre «...», e as frases que o código monta e entrega. O texto
    que explica o domínio ao modelo continua podendo dizer "a Bahrd", como em "a
    frota da Bahrd tem caminhão".
    """
    import re as _re

    from central_ia.agent import atendimento_real

    #: "Bahrd" sem "Monitoramento" logo depois.
    sozinho = _re.compile(r"\bLink\b(?!\s+Monitoramento)")

    achados: list[str] = []
    for caminho in RAIZ_PROMPTS.rglob("*.md"):
        texto = caminho.read_text(encoding="utf-8")
        for n, linha in enumerate(texto.splitlines(), 1):
            if linha.lstrip().startswith(">") and sozinho.search(linha):
                achados.append(f"{caminho.name}:{n} {linha.strip()[:60]}")
        achados += [
            f"{caminho.name}: {frase[:50]}"
            for frase in _re.findall(r"«[^«»]{10,400}»", texto, _re.DOTALL)
            if sozinho.search(frase)
        ]

    # E as frases que saem do código, montadas por nós e não pelo modelo.
    for nome, frase in (
        ("SEM_ATENDIMENTO_ABERTO", rota.SEM_ATENDIMENTO_ABERTO),
        ("DEPOIS_DO_FECHAMENTO", rota.DEPOIS_DO_FECHAMENTO),
        ("DESPEDIDA_PARA_HUMANO", rota.DESPEDIDA_PARA_HUMANO),
        ("DESPEDIDA_COM_OPERADOR", atendimento_real.DESPEDIDA_COM_OPERADOR),
        ("DESPEDIDA_SEM_OPERADOR", atendimento_real.DESPEDIDA_SEM_OPERADOR),
        ("PERGUNTA_DA_CAUSA", rota.PERGUNTA_DA_CAUSA),
    ):
        if sozinho.search(frase):
            achados.append(f"{nome}: {frase[:60]}")

    assert not achados, "a IA encolheu o nome da empresa:\n  " + "\n  ".join(achados)

    # E a regra escrita, para o teste acima não passar por silêncio.
    persona = (RAIZ_PROMPTS / "persona_core.md").read_text(encoding="utf-8")
    assert 'O nome da empresa é "Bahrd Monitoramento", sempre inteiro' in persona
    assert 'Nunca só\n"Bahrd"' in persona
