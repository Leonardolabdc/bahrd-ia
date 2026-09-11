"""A espera: "vou verificar" não pode virar escalonamento.

O comportamento que estes testes guardam saiu de uma demonstração real. O
motorista disse *"vou verificar"* e a IA respondeu *"vou te passar pra um
colega meu"* — entregando ao humano um caso que ia se resolver sozinho em dois
minutos. Era o playbook mandando escalar sem tentar uma segunda vez.
"""

from __future__ import annotations

from central_ia.agent.atendimento_real import (
    MARCA_AGUARDAR,
    MARCA_ESCALONAMENTO,
    contexto_inicial,
)
from central_ia.domain import eventos
from central_ia.orchestration.sessao_whatsapp import Sessoes

TELEFONE = "whatsapp:+5541999999999"
DADOS = {"placa": "GHI7J89", "interlocutor": "Antônio Ramos"}


def test_todo_evento_atendido_pela_ia_permite_esperar() -> None:
    """Sem espera, qualquer "peraí" volta a virar escalonamento.

    A exceção é deliberada: num veículo já marcado como roubado e em
    movimento, esperar é exatamente o que não se pode fazer. Na prática a
    triagem manda esse evento para o humano antes de qualquer conversa; a
    tupla vazia aqui é o cinto de segurança embaixo disso.
    """
    sem_espera = {t.codigo for t in eventos.CATALOGO if t.elegivel_ia and not t.esperas_s}
    assert sem_espera == {"ROUBO_ATIVO_MOVIMENTO"}


def test_espera_diminui_a_cada_retomada() -> None:
    """A segunda pausa é mais curta que a primeira.

    A primeira é alguém indo verificar. A segunda já é sinal de que a coisa
    não vai se resolver rápido, e insistir com o mesmo intervalo é a central
    esperando por esperar.
    """
    for tipo in eventos.CATALOGO:
        esperas = tipo.esperas_s
        assert list(esperas) == sorted(esperas, reverse=True), f"{tipo.codigo} não decresce"
        assert all(s > 0 for s in esperas)


def test_bateria_espera_duas_vezes_e_na_terceira_encerra() -> None:
    """A forma do comportamento, não o número do relógio.

    Os segundos foram encurtados para a demonstração e vão mudar de novo
    quando a Bahrd disser o valor de operação. O que não pode mudar é a
    escada: espera, espera menos, encerra.
    """
    bateria = eventos.REMOCAO_BATERIA
    assert bateria.retomadas_maximas == 2
    assert bateria.espera_da_retomada(0) == bateria.esperas_s[0]
    assert bateria.espera_da_retomada(1) < bateria.espera_da_retomada(0)
    # Terceira pausa: não há espera, e `pode_retomar` fecha a porta.
    assert bateria.espera_da_retomada(2) == 0


def test_panico_espera_uma_vez_so_e_depois_e_de_uma_pessoa() -> None:
    """O que protege o pânico é o **destino**, não o cronômetro.

    Este teste exigia que o pânico esperasse *menos* que a bateria — era 20 s
    contra 60 s. Em 25/08/2026 a espera do pânico subiu para 120 s, e a regra
    antiga se inverteu. Ela era uma proxy: o que de fato não se pode deixar
    passar não é o relógio, é o caso terminar sem ninguém olhando.

    E isso continua garantido, com folga: a bateria tem duas retomadas e depois
    **encerra sozinha** com desfecho do catálogo; o pânico tem uma só e depois
    vai para uma pessoa, porque não existe desfecho honesto para "ninguém
    atendeu num pânico".
    """
    assert eventos.PANICO.retomadas_maximas == 1
    assert eventos.REMOCAO_BATERIA.retomadas_maximas > 1

    # A garantia de verdade: pânico não tem como fechar sozinho por silêncio.
    assert eventos.PANICO.desfecho_sem_contato is None
    assert eventos.REMOCAO_BATERIA.desfecho_sem_contato is not None

    # E a espera continua cabendo dentro da janela de escalonamento.
    assert eventos.PANICO.esperas_s[0] <= eventos.PANICO.janela_s


def test_teto_de_retomadas_vem_da_lista_de_esperas() -> None:
    """Um campo só. Dois desalinhariam no dia em que alguém mexesse num deles."""
    for tipo in eventos.CATALOGO:
        assert tipo.retomadas_maximas == len(tipo.esperas_s)


def test_esperar_alem_da_janela_so_vale_em_modo_paralelo() -> None:
    """São prazos diferentes, e a diferença tem uma condição.

    `janela_s` é o prazo até o caso ser do humano; `esperas_s` é quanto a IA
    aguenta calada numa conversa viva. A IA só pode esperar além da janela se
    o playbook rodar em `modo_paralelo` — aí um operador já está com o caso e
    a espera não deixa ninguém desassistido. Fora disso, esperar mais que a
    janela é abandonar o evento.
    """
    for tipo in eventos.CATALOGO:
        if tipo.esperas_s and tipo.esperas_s[0] > tipo.janela_s:
            assert tipo.modo_paralelo, f"{tipo.codigo} espera além da janela sem par humano"


def test_instrucao_ensina_a_diferenca_entre_pausa_e_duvida() -> None:
    texto = contexto_inicial(eventos.REMOCAO_BATERIA, DADOS)
    assert MARCA_AGUARDAR in texto
    assert MARCA_ESCALONAMENTO in texto
    assert "vou verificar" in texto.lower()


def test_retomadas_tem_teto() -> None:
    """Insistir uma terceira vez é a central importunando quem está dirigindo."""
    s = Sessoes()
    sessao = s.abrir(TELEFONE, eventos.REMOCAO_BATERIA, "TEXTO", DADOS)

    primeira = sessao.proxima_espera_s
    assert sessao.pode_retomar
    assert primeira == eventos.REMOCAO_BATERIA.esperas_s[0]

    sessao.retomadas = 1
    assert sessao.pode_retomar
    assert sessao.proxima_espera_s < primeira, "a segunda espera é mais curta"

    sessao.retomadas = 2
    assert not sessao.pode_retomar, "na terceira pausa, o caso não volta para a IA"


def test_desfecho_sem_contato_esta_na_lista_branca() -> None:
    """Fechar sem contato só vale com desfecho que a política já autoriza.

    Sem esta trava, a saída "encerra sozinha" viraria uma porta lateral para
    fechar com qualquer coisa.
    """
    for tipo in eventos.CATALOGO:
        if tipo.desfecho_sem_contato:
            assert eventos.desfecho_permitido(tipo.codigo, tipo.desfecho_sem_contato)


def test_evento_critico_nunca_fecha_por_silencio() -> None:
    """A fronteira do "encerra em vez de escalar".

    Num pânico ou num roubo ativo, ninguém atender **é** informação — e não
    existe desfecho honesto para "não conseguimos falar com a pessoa". Fechar
    ali seria fechamento falso, que é o critério que a POC prometeu não violar.
    """
    for tipo in eventos.CATALOGO:
        if tipo.criticidade == "CRITICA":
            assert tipo.desfecho_sem_contato is None, f"{tipo.codigo} fecharia por silêncio"


def test_eventos_de_rotina_encerram_sozinhos() -> None:
    """É daqui que sai a contenção: os de maior volume não voltam para o humano."""
    for codigo in (
        "REMOCAO_BATERIA",
        "MOVIMENTO_SEM_IGNICAO",
        "VELOCIDADE_EXCEDIDA",
        "ULTRAPASSOU_LIMITE_VELOCIDADE",
        "VELOCIDADE_EXCEDIDA_CERCA_POLIGONO",
    ):
        tipo = eventos.por_codigo(codigo)
        assert tipo is not None
        assert tipo.desfecho_sem_contato, f"{codigo} ainda escala por falta de resposta"


def test_desfecho_sem_contato_nao_afirma_causa() -> None:
    """O nome do desfecho é lido por gente meses depois.

    "sem_resposta" diz o que houve. Qualquer nome que sugira causa confirmada
    transformaria um caso não apurado em um caso resolvido no relatório.
    """
    for tipo in eventos.CATALOGO:
        if tipo.desfecho_sem_contato:
            assert "sem_resposta" in tipo.desfecho_sem_contato


def test_sessao_encerrada_nao_retoma() -> None:
    """Relógio disparando numa conversa fechada seria a IA falando sozinha."""
    s = Sessoes()
    sessao = s.abrir(TELEFONE, eventos.REMOCAO_BATERIA, "TEXTO", DADOS)
    sessao.encerrar("encerrada_pela_ia", desfecho="veiculo_em_manutencao")

    assert not sessao.pode_retomar
