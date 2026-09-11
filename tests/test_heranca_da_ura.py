"""O que herdamos do fluxo da URA da Vetor — e o que recusamos herdar.

A URA da Bahrd roda há anos e conhece as causas reais de cada evento. Isso é
conhecimento de operação, e vale ouro: a nossa lista branca era em parte
suposição, a deles é validada na prática.

O que **não** se herda é a forma. Menu de cinco opções, "tecle 1 ou diga
apoio", caminho fixo por escolha — aquilo é desenho de sistema determinístico.
Copiar seria reconstruir uma URA usando um modelo de linguagem, que é a coisa
mais cara possível de se fazer com um modelo de linguagem.

A tradução: **o menu deles vira a nossa lista branca.** Mesma cobertura de
causas, interação oposta — a IA pergunta aberto e classifica no que ouviu, e o
cliente nunca vê a lista.
"""

from __future__ import annotations

from central_ia.agent.prompts import blocos_de_sistema
from central_ia.domain import eventos


def test_base_do_cliente_e_causa_valida() -> None:
    """A causa que faltava, e que a URA já tratava.

    Sem ela, o motorista que diz "isso aqui é meu pátio" não tinha desfecho: a
    IA cairia em "causa não confirmada", que é falso e gera trabalho humano
    para um caso legítimo.
    """
    assert eventos.desfecho_permitido("REMOCAO_BATERIA", "local_e_base_do_cliente")


def test_a_lista_branca_nao_virou_menu() -> None:
    """A trava continua invisível para o cliente.

    Se o playbook passasse a oferecer opções numeradas, teríamos gastado um
    modelo de raciocínio para reproduzir uma árvore de decisão.
    """
    playbook = " ".join(blocos_de_sistema(eventos.REMOCAO_BATERIA, "TEXTO")[-1].lower().split())

    assert "tecle 1" not in playbook
    assert "tecle 2" not in playbook
    assert "digite" not in playbook
    # E a pergunta de abertura continua aberta, não um cardápio.
    assert "você desligou a chave geral aí, ou o veículo tá em manutenção?" in playbook


def test_resposta_fora_da_pergunta_e_bem_vinda() -> None:
    """É onde a GenAI ganha da regra — e onde nascem os 8.000 eventos/mês.

    Na URA, tudo que não cabe em quatro opções cai na quinta ("outros") e vira
    atendimento humano. A IA precisa acolher a resposta que veio fora da
    pergunta em vez de repetir a pergunta.
    """
    playbook = " ".join(blocos_de_sistema(eventos.REMOCAO_BATERIA, "TEXTO")[-1].lower().split())
    assert "isso **é** resposta, e das boas" in playbook


def test_a_escolha_de_silenciar_e_do_cliente() -> None:
    """Há cliente que quer silêncio no pátio e cliente que quer saber de tudo.

    A URA pergunta; nós também perguntamos. Decidir por ela seria a IA
    escolhendo o que o cliente recebe.
    """
    playbook = " ".join(blocos_de_sistema(eventos.REMOCAO_BATERIA, "TEXTO")[-1].lower().split())
    assert "e não decida por ela" in playbook


def test_vocabulario_da_bahrd_esta_na_persona() -> None:
    """Os nomes das coisas, não as frases da gravação.

    Entram como glossário porque exemplo de frase em prompt vira roteiro
    recitado — foi assim que "botãozinho perto do banco" sobreviveu a três
    correções antes de alguém notar.
    """
    persona = " ".join(blocos_de_sistema(eventos.REMOCAO_BATERIA, "TEXTO")[0].lower().split())

    assert "central de operações da bahrd monitoramento" in persona
    assert "apoio operacional" in persona
    assert "inconsistência técnica" in persona
    assert "não são frases para recitar" in persona
