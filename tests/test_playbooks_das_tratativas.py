"""As regras de tratativa que os playbooks precisam manter escritas.

⚠️ **Este arquivo se chamava `test_guincho_credenciado.py`.** Guardava a
verificação anti-roubo do PB-MOV-SEM-IGNICAO: o motorista que **nomeasse
primeiro** a empresa certa fechava o caso sozinho, porque quem rouba um caminhão
não sabe qual guincho aquele cliente tem credenciado.

⛔ **A verificação inteira saiu em 03/09/2026**, e com ela o campo do cadastro, o
dado no contexto do modelo e a vigilância que observava a IA citando o nome antes
da hora. O motivo é de operação, não de código: *"não validamos qual guincho é na
realidade das tratativas aqui da empresa"* — a operação. O cadastro nunca foi
conferido contra o que acontece, então a prova apontava para uma referência que
ninguém mantém, e cobrava por isso o preço de manter o nome do guincho dentro do
contexto do modelo a cada turno.

O que sobrou no lugar é a pergunta de **duração da supressão**, e o que sobrou de
anti-roubo é o outro ramo: quem diz que o veículo deveria estar parado escala na
hora, sem mais perguntas.
"""

from __future__ import annotations

from central_ia.agent.prompts import blocos_de_sistema
from central_ia.domain import eventos


def test_playbook_pergunta_o_tempo_e_nao_a_empresa() -> None:
    """⚠️ **A pergunta mudou em 02/09/2026, por regra da Central.**

    O playbook mandava perguntar qual empresa estava rebocando e conferir o nome
    contra o guincho credenciado do cliente. Era uma verificação anti-roubo:
    quem está levando um veículo não sabe qual guincho aquele cliente tem.

    ⛔ **Essa verificação saiu**, e com ela a proteção. O que a Central pede
    agora é a **duração**, para suprimir os alarmes pelo tempo certo. A operação,
    repassando o gestor: *"não é para a IA perguntar qual empresa está fazendo o
    reboque, temos que colocar para ela perguntar por quanto tempo podemos
    desativar os alertas"*.

    O que sobrou de anti-roubo neste playbook é o outro ramo: quem diz que o
    veículo deveria estar parado escala na hora, sem mais perguntas.
    """
    blocos = blocos_de_sistema(eventos.MOVIMENTO_SEM_IGNICAO, "TEXTO")
    # Junta as quebras de linha: o texto é escrito em parágrafos, e a regra
    # pode cair partida entre duas linhas.
    playbook = " ".join(blocos[-1].lower().split())

    assert "por quanto tempo" in playbook
    assert "não pergunte qual empresa está rebocando" in playbook
    assert "duas horas" in playbook

    # ⛔ O exemplo não pode ensinar o que a regra tirou.
    assert "nunca diga o nome do guincho antes" not in playbook
    assert "guincho credenciado" not in playbook


def test_playbook_mostra_as_duas_formas_da_marca() -> None:
    """Com prazo e sem prazo, porque as duas acontecem e dão resultados diferentes."""
    playbook = " ".join(
        blocos_de_sistema(eventos.MOVIMENTO_SEM_IGNICAO, "TEXTO")[-1].lower().split()
    )

    assert "[[encerrar:reboque_autorizado:3h]]" in playbook
    assert "[[encerrar:reboque_autorizado]]" in playbook


def test_reboque_autorizado_continua_na_lista_branca() -> None:
    """O caminho novo fecha com o desfecho que já existia, não com um inventado."""
    assert eventos.desfecho_permitido("MOVIMENTO_SEM_IGNICAO", "reboque_autorizado")


def test_panico_separa_confusao_de_perigo() -> None:
    """"Não sei" é o caso mais comum de acionamento acidental, não um alarme.

    O playbook juntava confusão e perigo na mesma caixa e encerrava nos dois.
    Quem esbarrou no botão sem perceber não sabe mesmo o que houve — encerrar
    ali joga fora justamente o caso que a IA deveria resolver.
    """
    playbook = " ".join(blocos_de_sistema(eventos.PANICO, "TEXTO")[-1].lower().split())

    assert "confusa, mas falando livre" in playbook
    assert "não sei" in playbook
    assert "isso **não é sinal de risco**" in playbook
    # E a trava do outro lado continua: sinal de risco encerra sem mais perguntas.
    assert "não pergunte mais nada para ter certeza" in playbook


def test_panico_nunca_menciona_o_botao_antes_da_senha() -> None:
    """A regra que sobrevive a qualquer mudança neste playbook.

    ⚠️ **A segunda asserção mudou em 02/09/2026, e a regra ficou mais dura.**
    Ela exigia `"sem mencionar o botão"`, que era a regra antiga: podia falar
    do objeto **depois** de a pessoa ter falado à vontade.

    Num teste real a IA escreveu *"o sistema registrou que o veículo AAA1111
    disparou o botão de pânico"* na abertura, e depois *"aparece aqui que o
    botão foi acionado"*. A operação: *"tire a palavra botão, botãozinho e coisas
    similares para a IA não ter essa referência"*.

    Agora a palavra não existe em momento nenhum, e o que entra no lugar é o
    nome do **evento**. Nomear o evento não entrega nada; nomear o objeto diz a
    quem estiver lendo a tela junto qual é o equipamento de emergência do
    motorista.
    """
    playbook = " ".join(blocos_de_sistema(eventos.PANICO, "TEXTO")[-1].lower().split())
    assert "você nunca diz que houve um pânico" in playbook
    assert "sem nomear o alerta" in playbook
    assert 'a palavra "botão" não existe para você' in playbook


def test_panico_nao_ensina_a_dizer_botao_pelo_exemplo() -> None:
    """⛔ O playbook não pode ensinar pelo exemplo o que proíbe pela regra.

    As frases-modelo diziam *"aparece aqui que o botão foi acionado"*, e era
    delas que o modelo copiava. Proibição embaixo de exemplo contrário perde
    para o exemplo. As únicas ocorrências que sobram são as da tabela de
    substituição, onde a palavra aparece na coluna do que **não** se escreve.
    """
    playbook = blocos_de_sistema(eventos.PANICO, "TEXTO")[-1].lower()

    assert "botãozinho" not in playbook.replace('"botãozinho"', "")
    for frase in (
        "o botão foi acionado aí",
        "aparece aqui que o botão",
        "mencionar o botão",
    ):
        assert frase not in playbook, f"exemplo ensina a dizer «{frase}»"


# ─────────────── a aba Encerrados mede contenção da IA ───────────────


def test_encerrados_lista_so_o_que_a_ia_fechou_sozinha() -> None:
    """⛔ **Mudança de 03/09/2026, apontada pela operação.**

    A lista trazia junto casos que uma pessoa resolveu: *"a IA fez o contato,
    mas a resposta ficou no meio do caminho... Roberto ligou para a oficina,
    confirmou a ordem de serviço e encerrou"*. Isso não é contenção da IA, e a
    aba existe para medir contenção.
    """
    import asyncio

    from central_ia.api.rotas.painel import obter_encerrados

    encerrados = asyncio.run(obter_encerrados())

    assert encerrados.itens, "a lista não pode ficar vazia"
    assert all(e.encerrada_por == "ia" for e in encerrados.itens)


def test_o_denominador_da_contencao_sobrevive() -> None:
    """⚠️ **A armadilha desta mudança, e o motivo de os totais não serem filtrados.**

    A contenção do turno é `total_ia / (total_ia + total_operador)`. Filtrar os
    dois lugares zeraria o denominador e o cabeçalho anunciaria **100% de
    contenção** — inflando exatamente o número que a mudança queria proteger.

    A lista responde "o que a IA resolveu"; os números respondem "de quanto".
    """
    import asyncio

    from central_ia.api.rotas.painel import obter_encerrados

    encerrados = asyncio.run(obter_encerrados())

    assert encerrados.total_operador > 0, "sem denominador a contenção mente"
    assert len(encerrados.itens) < encerrados.total_ia + encerrados.total_operador
