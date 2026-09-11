"""A triagem do pânico não pode cair por ortografia.

⚠️ **Em 02/09/2026 um acento encerrou um pânico sem contato nenhum.** O modelo
respondeu `"confianca": "média"`, o `Literal` do Pydantic esperava `"media"`, e
a validação recusou. `TriagemInvalida` fez o que devia — nenhum contato, caso
para uma pessoa — mas nesta fase da POC não há pessoa, então o evento foi
encerrado e o cliente nunca soube que alguém tinha olhado.

A triagem é a chamada de maior consequência do sistema: ela decide se um alarme
de pânico é falso **antes** de qualquer contato. Ela falhar por acento é o pior
motivo possível para ela falhar.

Estes testes prendem as duas metades da regra:

1. o mesmo valor escrito de outro jeito **passa**;
2. valor que não existe no catálogo continua sendo **recusado**.

A segunda metade é a que impede a correção de virar frouxidão.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from central_ia.agent.triagem_panico import Triagem

BASE = {
    "probabilidade_real": 12,
    "evidencias": ["veículo parado no pátio há 40 min"],
    "justificativa": "Sem deslocamento e sem histórico de acionamento.",
}


# ─────────────────── o mesmo valor, escrito de outro jeito ───────────────────


@pytest.mark.parametrize(
    ("escrito", "esperado"),
    [
        ("média", "media"),  # ← o caso real de 02/09/2026
        ("Média", "media"),
        ("MEDIA", "media"),
        ("  baixa  ", "baixa"),
        ("Alta", "alta"),
        ("ALTA", "alta"),
    ],
)
def test_confianca_com_acento_ou_caixa_e_a_mesma_confianca(
    escrito: str, esperado: str
) -> None:
    triagem = Triagem(confianca=escrito, classificacao="falso_positivo", **BASE)
    assert triagem.confianca == esperado


@pytest.mark.parametrize(
    ("escrito", "esperado"),
    [
        ("FALSO_POSITIVO", "falso_positivo"),
        ("Possivel_Real", "possivel_real"),
        ("possível_real", "possivel_real"),
        (" inconclusivo ", "inconclusivo"),
    ],
)
def test_classificacao_tambem_tolera(escrito: str, esperado: str) -> None:
    triagem = Triagem(confianca="alta", classificacao=escrito, **BASE)
    assert triagem.classificacao == esperado


# ─────────────────────── e o que não existe continua fora ────────────────────


@pytest.mark.parametrize("inventado", ["muito alta", "média-alta", "", "9", "certeza"])
def test_confianca_inventada_continua_recusada(inventado: str) -> None:
    """⚠️ A tolerância é de ortografia, **não** de vocabulário.

    Aceitar valor fora do catálogo seria deixar o modelo inventar uma quarta
    confiança, e o `pode_encerrar_sozinha` compara com `"alta"` literalmente.
    """
    with pytest.raises(ValidationError):
        Triagem(confianca=inventado, classificacao="falso_positivo", **BASE)


@pytest.mark.parametrize("inventada", ["provavel_real", "falso", "real", "talvez"])
def test_classificacao_inventada_continua_recusada(inventada: str) -> None:
    with pytest.raises(ValidationError):
        Triagem(confianca="alta", classificacao=inventada, **BASE)


def test_numero_nao_vira_texto_pelo_caminho() -> None:
    """A normalização só toca em `str`; o resto do modelo segue como era."""
    with pytest.raises(ValidationError):
        Triagem(
            confianca="alta",
            classificacao="falso_positivo",
            probabilidade_real=170,
            evidencias=["x"],
            justificativa="y",
        )


# ──────────────── a consequência: o encerramento autônomo volta ──────────────


def test_o_acento_nao_muda_mais_o_destino_do_caso() -> None:
    """A prova de que a correção resolve o caso de 02/09.

    Antes: `"média"` levantava `ValidationError`, a triagem virava
    `TriagemInvalida` e o pânico encerrava sem contato. Agora a triagem existe,
    e é ela quem decide — que é o desenho.
    """
    com_acento = Triagem(confianca="média", classificacao="inconclusivo", **BASE)
    sem_acento = Triagem(confianca="media", classificacao="inconclusivo", **BASE)

    assert com_acento.confianca == sem_acento.confianca
    assert com_acento.exige_humano == sem_acento.exige_humano
    assert com_acento.pode_encerrar_sozinha == sem_acento.pode_encerrar_sozinha


def test_confianca_media_continua_sem_autorizar_encerramento() -> None:
    """⚠️ Tolerar o acento não pode afrouxar o portão.

    `pode_encerrar_sozinha` exige confiança **alta**. Se a normalização
    escorregasse e `"média"` virasse `"alta"`, um pânico inconclusivo passaria a
    poder encerrar sozinho — o oposto do que este módulo protege.
    """
    triagem = Triagem(
        confianca="média",
        classificacao="falso_positivo",
        probabilidade_real=3,
        evidencias=["x"],
        justificativa="y",
    )
    assert triagem.confianca == "media"
    assert triagem.pode_encerrar_sozinha is False
