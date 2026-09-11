"""O pânico notifica o cliente, e nunca encerra sozinho.

⚠️ **Dois defeitos vistos em teste real em 02/09/2026, um atrás do outro.**

1. A triagem quebrou por um acento (`"média"`), virou `TriagemInvalida`, e o
   caminho de falha não fez contato nenhum. Corrigido em `triagem_panico`.
2. Corrigido isso, a triagem passou a rodar e classificou acima do limiar —
   e aí **nada saiu mesmo assim**, porque o `_triar` barrava o contato inteiro.
   O caso foi encerrado por não haver operador. A operação: *"tem que chegar no
   número do cliente"* e *"fechou sozinho, não pode acontecer isso"*.

O que decidiu o segundo ponto foi o próprio template aprovado. O
`infra/templates-whatsapp/panico-mapa.json` diz "Acionamento do botão de
pânico", pergunta "Está tudo bem?" e traz um botão de ligação para o 0800: a
Bahrd já decidiu que o cliente é notificado. Barrar o envio era o código sendo
mais restritivo que a política dela.

**O que a triagem continua decidindo** é quem conduz. Acima do limiar ela não
autoriza a IA a encerrar, e o caso fica aberto esperando gente.
"""

from __future__ import annotations

from central_ia.api.rotas import whatsapp as rota
from central_ia.config import Settings
from central_ia.domain import eventos
from central_ia.orchestration.sessao_whatsapp import Sessao, Sessoes


def _cfg() -> Settings:
    return Settings(escalonamento_humano_ativo=False)


def _sessao(codigo: str) -> Sessao:
    return Sessoes().abrir(
        "+5541999998888", eventos.por_codigo(codigo), "TEXTO", {"interlocutor": "Bruno"}
    )


# ────────────────────────── a regra, no catálogo ─────────────────────────────


def test_o_panico_nao_encerra_sem_operador() -> None:
    assert eventos.PANICO.encerra_sem_operador is False


def test_os_demais_continuam_encerrando() -> None:
    """⚠️ A correção é do pânico, e o raio dela para aí.

    Para os outros eventos, encerrar sem operador continua razoável: o desfecho
    gravado é o próprio motivo, e quem lê a lista de encerrados vê o porquê.
    Se este teste cair, alguém generalizou a exceção.
    """
    assert eventos.REMOCAO_BATERIA.encerra_sem_operador is True
    assert eventos.MOVIMENTO_SEM_IGNICAO.encerra_sem_operador is True


# ──────────────────────── o que o `_encaminhar` faz ──────────────────────────


def test_panico_encaminhado_fica_aberto_na_fila() -> None:
    sessao = _sessao("PANICO")

    rota._encaminhar(_cfg(), sessao, "acima_do_limiar_de_risco", "90% ≥ 90%")

    assert not sessao.encerrada, "um pânico encerrado some de 'precisa de você'"
    assert sessao.viva
    assert sessao.escalada, "saiu das mãos da IA, mesmo sem operador de plantão"
    assert any("Aguardando uma pessoa" in p.descricao for p in sessao.trilha)


def test_o_motivo_do_escalonamento_fica_escrito() -> None:
    """Ficar aberto não pode custar o registro do porquê."""
    sessao = _sessao("PANICO")

    rota._encaminhar(_cfg(), sessao, "acima_do_limiar_de_risco", "90% ≥ 90% — caso de pessoa")

    assert any("90% ≥ 90%" in p.descricao for p in sessao.trilha)


def test_evento_comum_encaminhado_continua_encerrando() -> None:
    sessao = _sessao("REMOCAO_BATERIA")

    rota._encaminhar(_cfg(), sessao, "nega_a_causa", "O cliente negou as duas causas.")

    assert sessao.encerrada
    assert sessao.desfecho == "nega_a_causa"


# ─────────────── com operador ligado, nada disso muda o destino ──────────────


def test_com_operador_o_panico_escala_como_sempre() -> None:
    """⚠️ A correção é do modo **sem** operador. O outro lado da chave é o de sempre.

    Com `ESCALONAMENTO_HUMANO_ATIVO=true` existe alguém recebendo, e aí encerrar
    a sessão da IA é correto: o caso passou para uma pessoa de verdade.
    """
    sessao = _sessao("PANICO")
    cfg = Settings(escalonamento_humano_ativo=True)

    rota._encaminhar(cfg, sessao, "acima_do_limiar_de_risco", "90% ≥ 90%")

    assert sessao.encerrada
    assert sessao.escalada


# ─────────────────────── o template aprovado existe ──────────────────────────


def test_o_panico_tem_modelo_proprio_e_nao_o_generico() -> None:
    """⛔ **Voltou a ter o seu em 10/09/2026, e o motivo é o `PB-PANICO`.**

    Entre 02/09 e 10/09 o pânico usou o `evento_alerta`, que nomeia o tipo do
    evento em `{{1}}`. E o rótulo do `PANICO` no catálogo é, literalmente,
    `"Pânico"` — a palavra que o playbook proíbe ia impressa para o celular do
    cliente, em todo disparo. O texto humanizado que entrou no genérico em
    10/09 ("Identificamos uma ocorrência... precisamos confirmar uma
    informação") seria a segunda violação na mesma mensagem.

    A regra que manda em todas as outras, do `PB-PANICO.md`:

        "Você nunca diz que houve um pânico. (...) Se o alerta foi acionado de
         verdade, quem estiver junto do motorista passa a saber que a central
         percebeu, e é exatamente isso que não pode acontecer."
    """
    from central_ia.api.rotas.eventos import TEMPLATE_PROPRIO

    proprio = TEMPLATE_PROPRIO.get("PANICO")
    assert proprio is not None, "o pânico voltou a usar o modelo genérico"
    # Os quatro, nas mesmas combinações de mapa e nome que os outros eventos.
    # Nenhuma delas afrouxa a regra: o que o playbook proíbe é nomear o evento,
    # e nenhum dos quatro o nomeia.
    assert proprio.mapa == "evento_panico_saudacao_mapa"
    assert proprio.texto == "evento_panico_saudacao"
    assert proprio.mapa_reserva == "evento_panico_mapa"
    assert proprio.texto_reserva == "evento_panico"


def test_o_texto_do_panico_nao_entrega_o_que_foi_detectado() -> None:
    """A trava de verdade: o corpo aprovado, palavra por palavra.

    ⚠️ **Apontar para o modelo certo não basta.** O `evento_panico` já existiu
    dizendo "Acionamento do botão de pânico" — apontar para ele naquela versão
    teria sido pior que usar o genérico. O que protege é o texto, e é ele que
    este teste lê, do mesmo `.json` que a aplicação lê.
    """
    from central_ia.api.rotas.eventos import TEMPLATE_PROPRIO
    from central_ia.integrations.mensageria import modelos

    proprio = TEMPLATE_PROPRIO["PANICO"]
    corpos = {
        proprio.texto: modelos.corpo(proprio.texto, ["bom dia, João", "AAA1111"]),
        proprio.mapa: modelos.corpo(proprio.mapa, ["bom dia, João", "AAA1111"]),
        proprio.texto_reserva: modelos.corpo(proprio.texto_reserva, ["AAA1111"]),
        proprio.mapa_reserva: modelos.corpo(proprio.mapa_reserva, ["AAA1111"]),
    }

    for nome, corpo in corpos.items():
        assert corpo is not None, f"modelo {nome} fora do manifesto"
        baixo = corpo.lower()
        for proibida in ("pânico", "panico", "alerta", "emergência", "ocorrência", "sinal"):
            assert proibida not in baixo, f"{nome} diz '{proibida}'"
        # E continua sendo uma checagem de rotina que pede resposta.
        assert "AAA1111" in corpo, f"{nome}: a placa é o dado que identifica"
        assert corpo.rstrip().endswith("?"), f"{nome}: termina em pergunta"
        assert "{{" not in corpo, f"{nome}: sobrou marcador de parâmetro"

def test_um_tudo_bem_sozinho_nao_fecha_panico() -> None:
    """A trava que substituiu o template próprio, e ela precisa existir.

    Sem autorização da triagem, `triagem_autoriza_encerrar` é falso, e é ele que
    permite o fechamento autônomo. Se este teste cair, o botão "Está tudo bem!"
    volta a poder encerrar um pânico sozinho.
    """
    sessao = _sessao("PANICO")

    assert sessao.triagem_autoriza_encerrar is False
