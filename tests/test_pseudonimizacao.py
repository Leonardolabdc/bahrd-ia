"""A LLM nunca pode ver nome, placa ou endereço reais do cliente.

Etapa 2 da disciplina: "sanitização de PII antes de qualquer chamada ao LLM"
é critério de anulação se faltar. A garantia mora aqui, não no prompt — ver
o cabeçalho de `agent/pseudonimizacao.py` para o porquê das duas camadas.
"""

from __future__ import annotations

from central_ia.agent.pseudonimizacao import montar_mapa, sanitizar_historico
from central_ia.ports.llm import Mensagem


def _mapa_completo():
    return montar_mapa(
        nome="Leonardo Campos",
        placa="ABC1D23",
        endereco="Rua Comendador Roseira, 123 - Prado Velho, Curitiba",
    )


# ───────────────────────── camada 1 · dado conhecido ─────────────────────────


def test_sanitizar_troca_nome_placa_e_endereco() -> None:
    mapa = _mapa_completo()
    texto = (
        "Olá, bom dia, Leonardo Campos! Identificamos uma ocorrência no "
        "veículo ABC1D23, em Rua Comendador Roseira, 123 - Prado Velho, "
        "Curitiba. Está tudo bem?"
    )
    sanitizado = mapa.sanitizar(texto)

    assert "Leonardo Campos" not in sanitizado
    assert "ABC1D23" not in sanitizado
    assert "Prado Velho" not in sanitizado
    assert "Cliente" in sanitizado
    assert "VEIC-001" in sanitizado


def test_sanitizar_e_case_insensitive() -> None:
    # A IA ou o cliente podem repetir o nome com capitalização diferente —
    # "leonardo campos" ainda é o mesmo dado real, e tem que ser pego.
    mapa = _mapa_completo()
    assert "leonardo campos" not in mapa.sanitizar("aqui é o leonardo campos mesmo")


def test_reidentificar_desfaz_a_troca() -> None:
    mapa = _mapa_completo()
    resposta_da_ia = "Entendi, Cliente. Chave geral desligada no VEIC-001."
    real = mapa.reidentificar(resposta_da_ia)

    assert "Leonardo Campos" in real
    assert "ABC1D23" in real
    assert "Cliente" not in real
    assert "VEIC-001" not in real


def test_ida_e_volta_preserva_o_resto_da_frase() -> None:
    # Sanitizar e reidentificar em sequência devolve a frase original —
    # nada além do nome/placa/endereço pode mudar no caminho.
    mapa = _mapa_completo()
    original = "Leonardo Campos, o ABC1D23 está parado de novo?"
    assert mapa.reidentificar(mapa.sanitizar(original)) == original


def test_campo_ausente_nao_vira_par_no_mapa() -> None:
    # Nem todo evento tem endereço. Campo None não deve virar um par
    # "None → apelido", que sanitizaria a palavra "None" do texto por engano.
    mapa = montar_mapa(nome="Leonardo Campos", placa="ABC1D23", endereco=None)
    sanitizado = mapa.sanitizar("Isso aqui é None mesmo, não endereço nenhum.")
    assert "None" in sanitizado
    assert "o local informado" not in sanitizado


# ───────────────────── camada 2 · dado desconhecido, por padrão ──────────────


def test_sanitizar_mascara_cpf_nao_cadastrado() -> None:
    mapa = _mapa_completo()
    sanitizado = mapa.sanitizar("Meu CPF é 123.456.789-00, pode confirmar?")
    assert "123.456.789-00" not in sanitizado
    assert "[CPF]" in sanitizado


def test_sanitizar_mascara_telefone_de_terceiro() -> None:
    mapa = _mapa_completo()
    sanitizado = mapa.sanitizar("Liga pro meu gestor no (41) 98888-7777.")
    assert "98888-7777" not in sanitizado
    assert "[TELEFONE]" in sanitizado


def test_sanitizar_mascara_email() -> None:
    mapa = _mapa_completo()
    sanitizado = mapa.sanitizar("Manda um relatório pra joao.silva@exemplo.com.br")
    assert "joao.silva@exemplo.com.br" not in sanitizado
    assert "[EMAIL]" in sanitizado


def test_camada_2_nao_e_reidentificada() -> None:
    # CPF/telefone/e-mail viram marcador fixo — não tem valor real guardado
    # para devolver, e não deveria devolver: a IA nunca precisou do dado cru.
    mapa = _mapa_completo()
    assert mapa.reidentificar("Recebi o [CPF] e o [TELEFONE].") == (
        "Recebi o [CPF] e o [TELEFONE]."
    )


# ───────────────────────── sanitizar_historico ───────────────────────────────


def test_sanitizar_historico_nao_muta_a_lista_original() -> None:
    mapa = _mapa_completo()
    original = [Mensagem(papel="user", conteudo="Aqui é o Leonardo Campos")]
    sanitizado = sanitizar_historico(original, mapa)

    assert "Leonardo Campos" in original[0].conteudo, "a sessão de verdade não pode mudar"
    assert "Leonardo Campos" not in sanitizado[0].conteudo


def test_sanitizar_historico_preserva_o_papel_de_cada_fala() -> None:
    mapa = _mapa_completo()
    original = [
        Mensagem(papel="assistant", conteudo="Olá, Leonardo Campos!"),
        Mensagem(papel="user", conteudo="oi"),
    ]
    sanitizado = sanitizar_historico(original, mapa)

    assert [m.papel for m in sanitizado] == ["assistant", "user"]
