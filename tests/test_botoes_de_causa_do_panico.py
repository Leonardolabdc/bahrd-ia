"""Os botões de causa mudam com o evento.

⚠️ **Em 02/09/2026 o cliente tocou em «Está tudo bem!» num pânico e recebeu
«Em manutenção · Desliguei a chave · Outro motivo».** Nenhuma das três responde
à pergunta de um acionamento de emergência, e a do meio é sobre um equipamento
que não tem relação nenhuma com o caso.

Os rótulos vieram do Leonardo, repassando a Central: «Acionei sem querer» e
«Outro motivo». O terceiro é escolha nossa, e entrou por ser o único que **muda
o destino do caso**: quem diz que não foi ele está dizendo que alguém ou alguma
coisa acionou o alerta, e isso é de uma pessoa.

⚠️ Estes são **mensagem interativa**, mandada por nós na hora. Os botões do
cartão de abertura («Preciso de ajuda!» e «Está tudo bem!») são do modelo
aprovado na Meta e só mudam com aprovação nova.
"""

from __future__ import annotations

import pytest

from central_ia.api.rotas import whatsapp as rota

TODOS_OS_CODIGOS = [t.codigo for t in __import__(
    "central_ia.domain.eventos", fromlist=["CATALOGO"]
).CATALOGO]


def test_o_panico_tem_botoes_proprios() -> None:
    rotulos = [r for _, r in rota.causas_do_evento("PANICO")]

    assert rotulos == ["Acionei sem querer", "Não fui eu", "Outro motivo"]


def test_o_panico_nao_oferece_manutencao_nem_chave_geral() -> None:
    """⛔ Foi o defeito: oferecer causa de bateria num evento de emergência."""
    rotulos = [r for _, r in rota.causas_do_evento("PANICO")]

    assert "Em manutenção" not in rotulos
    assert "Desliguei a chave" not in rotulos


def test_os_demais_eventos_continuam_com_as_de_sempre() -> None:
    """⚠️ A troca é do pânico, e o raio dela para aí."""
    for codigo in ("REMOCAO_BATERIA", "MOVIMENTO_SEM_IGNICAO", "VELOCIDADE_EXCEDIDA"):
        assert rota.causas_do_evento(codigo) == rota.CAUSAS


@pytest.mark.parametrize("codigo", TODOS_OS_CODIGOS)
def test_todo_botao_tem_nota_para_o_modelo(codigo: str) -> None:
    """Botão sem nota é botão que o modelo recebe sem saber o que significa.

    O `_atender_causa` faz `NOTA_POR_CAUSA[ident]` direto, sem `get`: um botão
    novo sem nota derrubaria o atendimento com `KeyError` no toque do cliente.
    """
    for ident, rotulo in rota.causas_do_evento(codigo):
        assert ident in rota.NOTA_POR_CAUSA, f"«{rotulo}» não tem nota"


@pytest.mark.parametrize("codigo", TODOS_OS_CODIGOS)
def test_nenhum_rotulo_estoura_o_limite_da_meta(codigo: str) -> None:
    """A Meta corta rótulo de botão em 20 caracteres."""
    for _, rotulo in rota.causas_do_evento(codigo):
        assert len(rotulo) <= 20, f"«{rotulo}» tem {len(rotulo)}"


def test_a_nota_do_nao_fui_eu_manda_escalar_sem_perguntar() -> None:
    """⛔ Quem não acionou o alerta não é caso de conversa, é caso de pessoa."""
    nota = rota.NOTA_POR_CAUSA[rota.BOTAO_NAO_FUI_EU].lower()

    assert "escale imediatamente" in nota
    assert "não encerre" in nota


def test_a_nota_do_sem_querer_proibe_a_palavra_botao() -> None:
    """A regra do `PB-PANICO` precisa valer também no atalho do botão.

    A nota entra no histórico do modelo e é a última coisa que ele lê antes de
    escrever. Sem a proibição aqui, o atalho contorna o playbook.
    """
    nota = rota.NOTA_POR_CAUSA[rota.BOTAO_SEM_QUERER].lower()

    assert "não use a palavra «botão»" in nota
    assert "acionamento_acidental_confirmado" in nota
