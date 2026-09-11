"""Quem pergunta ainda não decidiu, e por isso não fecha o caso.

⛔ **Visto num pânico real em 03/09/2026, com o Gemini 2.5 Flash Lite.** A IA
escreveu, na mesma mensagem:

    "Então posso registrar como acionamento sem querer e encerrar por aqui,
    Luciando?"

e emitiu `[[ENCERRAR:acionamento_acidental_confirmado]]` no mesmo turno. O
código obedeceu a marca, o caso foi para «Encerrados», e a pergunta chegou ao
celular sem ninguém para responder. O cliente ficou esperando; o sistema achou
que tinha acabado.

⚠️ **A contradição é do modelo, mas a detecção é nossa** e não precisa de modelo
nenhum. O `PB-PANICO` manda confirmar antes de fechar, e um desfecho que sai
junto com a confirmação é o oposto disso.

Vale para qualquer modelo, inclusive o Sonnet num dia ruim. Num pânico, o custo
de errar aqui é fechar um caso que ninguém confirmou.
"""

from __future__ import annotations

from central_ia.api.rotas.whatsapp import _termina_em_pergunta


class TestTerminaEmPergunta:
    """O detector, isolado. É determinístico de propósito: sem LLM no caminho."""

    def test_a_frase_que_causou_o_defeito(self) -> None:
        assert _termina_em_pergunta(
            "Então posso registrar como acionamento sem querer e encerrar por "
            "aqui, Luciando?"
        )

    def test_fechamento_afirmativo_passa(self) -> None:
        """O caso normal: a IA conclui e fecha. Nada a travar aqui."""
        assert not _termina_em_pergunta(
            "Certo, Luciando. Registrei como acionamento acidental e encerro por aqui."
        )

    def test_pergunta_no_meio_nao_trava(self) -> None:
        """⚠️ A distinção que faz este detector ser usável.

        A IA legitimamente recapitula antes de fechar. Ali a pergunta já foi
        respondida no turno anterior, e travar por causa dela impediria todo
        encerramento educado.
        """
        assert not _termina_em_pergunta(
            "Você disse que foi sem querer, certo? Então registrei assim e "
            "encerro por aqui."
        )

    def test_tolera_o_que_vem_depois_do_interrogativo(self) -> None:
        """O modelo escreve como gente: fecha aspas, põe espaço, usa parêntese."""
        for frase in (
            "Posso encerrar por aqui? ",
            'Posso encerrar por aqui?"',
            "Posso encerrar por aqui?)",
        ):
            assert _termina_em_pergunta(frase), frase

    def test_mensagem_vazia_nao_e_pergunta(self) -> None:
        """⛔ Turno vazio já tem tratamento próprio; não pode virar pergunta aqui."""
        assert not _termina_em_pergunta("")
        assert not _termina_em_pergunta("   ")


class TestNaoQuebraOFluxoNormal:
    """A trava não pode custar os encerramentos legítimos.

    Toda a contenção da IA passa por aqui. Um detector que barrasse fechamento
    comum trocaria um defeito raro por indisponibilidade diária, que é
    exatamente o negócio que o resto do sistema recusa fazer.
    """

    def test_as_despedidas_reais_do_projeto_nao_travam(self) -> None:
        for frase in (
            "Beleza. Os avisos desse veículo ficarão desconsiderados enquanto "
            "durar o transporte. Boa viagem!",
            "Entendi. Já registrei como chave geral desligada no pátio, então o "
            "alerta encerra aqui. Boa noite, Antônio!",
            "Certo, Regina. Registrei como reboque autorizado e vou "
            "desconsiderar os alertas pelas próximas 3 horas. Obrigada!",
        ):
            assert not _termina_em_pergunta(frase), frase
