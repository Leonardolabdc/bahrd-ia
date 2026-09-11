"""O ciclo de vida de uma conversa de WhatsApp: abre, conduz, encerra.

Roda sem rede: exercita as regras que não podem depender do modelo nem do
Twilio — cor por evidência, limite de turnos, validade da sessão e a trava do
desfecho contra a lista branca.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from central_ia.agent.atendimento_real import contexto_inicial
from central_ia.domain import eventos
from central_ia.orchestration.sessao_whatsapp import (
    JANELA_DE_ATENDIMENTO,
    MAX_TURNOS_IA,
    VALIDADE,
    Sessoes,
)

TELEFONE = "whatsapp:+5511999999999"
DADOS = {
    "placa": "XYZ4E56",
    "interlocutor": "Marcos Pereira",
    "posição": "Rodovia Régis Bittencourt, Curitiba - PR",
}


def _sessoes() -> Sessoes:
    return Sessoes()


def test_sessao_carrega_posicao_para_o_mapa() -> None:
    """Sem isso o mapa some justamente na tela ao vivo.

    É onde alguém acompanha a conversa acontecendo — e é a tela em que ver o
    caminhão junto do diálogo tem mais valor, não menos.
    """
    s = _sessoes()
    sessao = s.abrir(TELEFONE, eventos.REMOCAO_BATERIA, "TEXTO", DADOS)

    assert hasattr(sessao, "latitude")
    assert hasattr(sessao, "longitude")

    sessao.latitude, sessao.longitude = -21.1704, -47.8103
    assert -90 <= sessao.latitude <= 90
    assert -180 <= sessao.longitude <= 180


def test_um_numero_tem_uma_conversa_por_vez() -> None:
    """Duas seriam duas IAs escrevendo para a mesma pessoa, cada uma cega da outra."""
    s = _sessoes()
    primeira = s.abrir(TELEFONE, eventos.REMOCAO_BATERIA, "TEXTO", DADOS)
    segunda = s.abrir(TELEFONE, eventos.PANICO, "TEXTO", DADOS)

    assert s.ativa(TELEFONE) is segunda
    assert s.ativa(TELEFONE) is not primeira


def test_sessao_parada_deixa_de_aceitar_resposta() -> None:
    """Resposta que chega dias depois não entra numa conversa que ninguém lembra."""
    s = _sessoes()
    sessao = s.abrir(TELEFONE, eventos.REMOCAO_BATERIA, "TEXTO", DADOS)
    sessao.ultima_em = datetime.now(UTC) - VALIDADE - timedelta(seconds=1)

    assert sessao.expirada
    assert s.ativa(TELEFONE) is None


def test_validade_e_a_janela_da_meta() -> None:
    """Amarradas de propósito, não por coincidência.

    Qualquer valor menor inventa um segundo prazo, mais curto que o real, e o
    atendimento se perde no intervalo entre os dois. Maior seria pior: passada
    a janela, a Meta exige template novo e a conversa recomeça de qualquer
    jeito — manter a sessão viva ali só criaria um atendimento fantasma.
    """
    assert VALIDADE == JANELA_DE_ATENDIMENTO


@pytest.mark.parametrize(
    ("pausa", "o_que_a_pessoa_estava_fazendo"),
    [
        (timedelta(minutes=2), "leu e respondeu"),
        (timedelta(minutes=40), "desceu, foi na oficina do Carlão e voltou"),
        (timedelta(hours=3), "estava dirigindo e só parou depois"),
        (timedelta(hours=23), "só viu a mensagem no dia seguinte"),
    ],
)
def test_pausa_normal_do_motorista_nao_mata_a_conversa(
    pausa: timedelta, o_que_a_pessoa_estava_fazendo: str
) -> None:
    """**Era o bug de 30 minutos.**

    Depois do "fico no aguardo" a IA cutuca duas vezes, 60 s e 30 s, e para.
    Com validade de meia hora, quem foi verificar de verdade voltava para uma
    conversa morta e recebia o menu de teste da POC no lugar da continuação —
    e a Meta, do lado dela, teria entregue a resposta de graça.
    """
    s = _sessoes()
    sessao = s.abrir(TELEFONE, eventos.REMOCAO_BATERIA, "TEXTO", DADOS)
    sessao.ultima_em = datetime.now(UTC) - pausa

    assert not sessao.expirada, f"morreu enquanto a pessoa {o_que_a_pessoa_estava_fazendo}"
    assert s.ativa(TELEFONE) is not None


def test_encerrada_sai_da_ativa_mas_fica_no_historico() -> None:
    """Conversa que some da tela ao terminar é conversa que ninguém confere."""
    s = _sessoes()
    sessao = s.abrir(TELEFONE, eventos.REMOCAO_BATERIA, "TEXTO", DADOS)
    sessao.encerrar("encerrada_pela_ia", desfecho="veiculo_em_manutencao")

    assert s.ativa(TELEFONE) is None
    assert s.por_id(sessao.ocorrencia_id) is sessao
    assert sessao in s.todas()


def test_cor_do_panico_segue_a_evidencia() -> None:
    """Pânico de 15% em vermelho-crítico ensina o operador a ignorar vermelho."""
    s = _sessoes()
    sessao = s.abrir(TELEFONE, eventos.PANICO, "TEXTO", DADOS)

    assert sessao.grau == "critica", "sem triagem, vale a criticidade do catálogo"

    sessao.probabilidade_real = 15
    assert sessao.grau == "media"

    sessao.probabilidade_real = 60
    assert sessao.grau == "alta"

    sessao.probabilidade_real = 94
    assert sessao.grau == "critica"


def test_evento_comum_nao_muda_de_cor() -> None:
    """Só evento com triagem tem probabilidade; o resto mantém a faixa do catálogo."""
    s = _sessoes()
    sessao = s.abrir(TELEFONE, eventos.VELOCIDADE_EXCEDIDA, "TEXTO", DADOS)
    assert sessao.probabilidade_real is None
    assert sessao.grau == "baixa"


def test_contexto_inicial_lista_a_lista_branca_do_evento() -> None:
    """A IA precisa saber com o que pode fechar — senão inventa desfecho."""
    texto = contexto_inicial(eventos.REMOCAO_BATERIA, DADOS)
    for desfecho in eventos.REMOCAO_BATERIA.desfechos_permitidos:
        assert desfecho in texto


def test_contexto_de_evento_sem_lista_branca_manda_escalar() -> None:
    """Roubo ativo não tem desfecho nenhum: o texto tem de dizer isso."""
    texto = contexto_inicial(eventos.ROUBO_ATIVO_MOVIMENTO, DADOS)
    assert "nenhum" in texto.lower()
    assert "escalonamento" in texto.lower()


def test_as_tres_faixas_da_triagem_nao_se_sobrepoem() -> None:
    """Toda probabilidade cai em exatamente uma faixa, e sempre na mesma."""
    from central_ia.agent.triagem_panico import Triagem

    def triar(prob: int, confianca: str = "alta", classe: str = "falso_positivo") -> Triagem:
        return Triagem(
            classificacao=classe,  # type: ignore[arg-type]
            confianca=confianca,  # type: ignore[arg-type]
            probabilidade_real=prob,
            evidencias=["x"],
            justificativa="y",
        )

    assert triar(95).faixa == "humano_assume"
    assert triar(90).faixa == "humano_assume"
    assert triar(89).faixa == "ia_atende_operador_revisa"
    assert triar(21).faixa == "ia_atende_operador_revisa"
    assert triar(20).faixa == "ia_encerra"
    assert triar(5).faixa == "ia_encerra"

    # Nenhuma probabilidade pode cair em duas faixas ao mesmo tempo.
    for prob in range(0, 101):
        t = triar(prob)
        assert not (t.exige_humano and t.pode_encerrar_sozinha)


def test_probabilidade_baixa_sem_confianca_nao_encerra_sozinha() -> None:
    """15% com confiança baixa quer dizer "não sei", não "é falso"."""
    from central_ia.agent.triagem_panico import Triagem

    base = {"probabilidade_real": 10, "evidencias": ["x"], "justificativa": "y"}

    assert Triagem(classificacao="falso_positivo", confianca="alta", **base).pode_encerrar_sozinha
    assert not Triagem(
        classificacao="falso_positivo", confianca="media", **base
    ).pode_encerrar_sozinha
    assert not Triagem(
        classificacao="inconclusivo", confianca="alta", **base
    ).pode_encerrar_sozinha


def test_encerrar_sozinha_exige_que_alguem_tenha_respondido() -> None:
    """Fechar sem resposta é fechar por silêncio — e silêncio é informação."""
    s = _sessoes()
    sessao = s.abrir(TELEFONE, eventos.PANICO, "TEXTO", DADOS)
    sessao.triagem_autoriza_encerrar = True

    assert not sessao.pode_encerrar_sem_operador, "ninguém respondeu ainda"

    sessao.registrar_cliente("tá tudo certo por aqui")
    assert sessao.pode_encerrar_sem_operador


def test_evento_comum_nao_precisa_de_revisao() -> None:
    """A contenção vem daqui: bateria e velocidade fecham sozinhas, sem faixa."""
    s = _sessoes()
    bateria = s.abrir(TELEFONE, eventos.REMOCAO_BATERIA, "TEXTO", DADOS)
    assert not bateria.fechamento_precisa_de_revisao

    panico = s.abrir("whatsapp:+5511888888888", eventos.PANICO, "TEXTO", DADOS)
    assert panico.fechamento_precisa_de_revisao, "sem triagem decisiva, quem fecha é gente"
    panico.triagem_autoriza_encerrar = True
    assert not panico.fechamento_precisa_de_revisao


def test_limite_de_turnos_e_menor_que_qualquer_conversa_infinita() -> None:
    """Conversa que não fecha em poucos turnos não vai fechar."""
    assert 1 <= MAX_TURNOS_IA <= 8


def test_desfecho_fora_da_lista_branca_nao_fecha_panico() -> None:
    """A IA propõe; quem autoriza é o catálogo.

    Esta é a trava que impede um desfecho inventado pelo modelo virar
    ocorrência encerrada.
    """
    assert eventos.desfecho_permitido("PANICO", "acionamento_acidental_confirmado")
    assert not eventos.desfecho_permitido("PANICO", "tudo_certo_por_aqui")
    assert not eventos.desfecho_permitido(
        "ROUBO_ATIVO_MOVIMENTO", "acionamento_acidental_confirmado"
    )
