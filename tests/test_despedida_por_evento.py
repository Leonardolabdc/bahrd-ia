"""A última frase do atendimento muda com o evento.

**Observado em 24/08/2026.** A IA fechou um movimento sem ignição com *"Boa
viagem!"* — só que o caminhão estava **no guincho**, e quem atendeu podia nem
estar perto dele.

Desejar boa viagem ali soa automático, e automático é justamente o que denuncia
que não tem gente do outro lado. O contrário do que a POC quer provar.
"""

from __future__ import annotations

import pytest

from central_ia.agent.atendimento_real import despedida_de_encerramento


@pytest.mark.parametrize(
    "codigo",
    ["MOVIMENTO_SEM_IGNICAO", "REMOCAO_BATERIA"],
)
def test_veiculo_parado_nao_recebe_boa_viagem(codigo: str) -> None:
    """Guincho e manutenção: ninguém está dirigindo."""
    frase = despedida_de_encerramento(codigo, "João da Silva")

    assert "viagem" not in frase.lower()


@pytest.mark.parametrize(
    "codigo",
    ["VELOCIDADE_EXCEDIDA", "ULTRAPASSOU_LIMITE_VELOCIDADE"],
)
def test_dirigindo_ainda_recebe_boa_viagem(codigo: str) -> None:
    """Onde a pessoa está ao volante, a frase cabe — e soa natural."""
    assert "Boa viagem" in despedida_de_encerramento(codigo, "Carla")


def test_evento_desconhecido_cai_no_neutro() -> None:
    """O padrão serve para quem dirige, para quem parou e para quem observa."""
    frase = despedida_de_encerramento("EVENTO_QUE_NAO_EXISTE", "Antônio")

    assert "viagem" not in frase.lower()
    assert "Antônio" in frase


def test_usa_so_o_primeiro_nome() -> None:
    """Central chama pelo primeiro nome. Nome completo soa a cadastro."""
    frase = despedida_de_encerramento("REMOCAO_BATERIA", "João da Silva")

    assert "João" in frase
    assert "Silva" not in frase


def test_sem_nome_nao_deixa_virgula_solta() -> None:
    """Ficha sem motorista é comum — a frase não pode sair quebrada."""
    frase = despedida_de_encerramento("REMOCAO_BATERIA", None)

    assert ", ." not in frase
    assert " ," not in frase
    assert frase.strip()


def test_nome_de_ficha_com_grupo_pega_so_a_pessoa() -> None:
    """A amostra traz `"Antônio, GRUPO X"` — o grupo não é o interlocutor."""
    assert "GRUPO" not in despedida_de_encerramento("REMOCAO_BATERIA", "Antônio, GRUPO X")
