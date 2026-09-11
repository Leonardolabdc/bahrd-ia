"""A chave que desliga a triagem prévia, e o que ela custa.

⛔ **`TRIAGEM_PREVIA_ATIVA=false` é modo de teste.** Ligada, todo evento com
`exige_triagem_previa` é classificado **antes de qualquer contato**: acima de
`LIMIAR_ESCALONAMENTO` o caso é de uma pessoa e ninguém escreve para o
motorista. É o princípio de que a IA não conversa com quem pode estar sob
coação. Desligada, o pânico corre como remoção de bateria.

⚠️ **Existe enquanto a fonte for `amostra`.** Sem acesso à plataforma da Bahrd,
um veículo fora dos três de `rastreamento/amostra.py` chega à triagem sem
posição, rota nem histórico. O prompt manda arredondar para cima diante de dado
ausente — e faz certo — então todo pânico de teste ia para a fila humana. Somado
a isso, em 02/09/2026 a triagem falhou em 8 dos 9 disparos do dia, sempre no
mesmo lugar: o raciocínio comia o orçamento e o JSON voltava cortado.

Decisão da operação: simplificar agora, e refazer a filtragem de
casos possivelmente reais quando a API da Bahrd entrar, com dado de verdade.

⚠️ O container recebe o `.env` como variável de ambiente, então `_env_file=None`
não basta para ler o padrão — é preciso limpar a variável.
"""

from __future__ import annotations

import pytest

from central_ia.config import Settings

CHAVE = "TRIAGEM_PREVIA_ATIVA"


def test_o_padrao_e_triar(monkeypatch: pytest.MonkeyPatch) -> None:
    """⛔ Se este teste cair, a triagem do pânico virou opt-in.

    Um ambiente novo, sem a chave escrita em lugar nenhum, tem de nascer com a
    avaliação prévia de pé. Esquecer de ligar não pode ser o mesmo que decidir
    desligar.
    """
    monkeypatch.delenv(CHAVE, raising=False)

    assert Settings(_env_file=None).triagem_previa_ativa is True


def test_a_chave_desliga_por_ambiente(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CHAVE, "false")

    assert Settings(_env_file=None).triagem_previa_ativa is False


def test_o_catalogo_continua_exigindo_triagem(monkeypatch: pytest.MonkeyPatch) -> None:
    """⭐ A chave é de ambiente; a política continua escrita no catálogo.

    Desligar por variável é reversível e aparece no `.env`. Apagar
    `exige_triagem_previa` do pânico seria a mesma coisa sem volta, e ninguém
    lembraria de recolocar quando a API da Bahrd entrasse.
    """
    from central_ia.domain import eventos

    monkeypatch.setenv(CHAVE, "false")

    assert eventos.PANICO.exige_triagem_previa is True
    assert eventos.ROUBO_ATIVO_MOVIMENTO.exige_triagem_previa is True
    assert eventos.REMOCAO_BATERIA.exige_triagem_previa is False


def test_nao_se_confunde_com_o_panico_autonomo(monkeypatch: pytest.MonkeyPatch) -> None:
    """Duas chaves, dois momentos, e misturá-las apagaria uma proteção.

    `PANICO_AUTONOMO` decide se a IA pode **encerrar** um pânico sozinha, no fim
    da conversa. Esta decide se ela pode **começar** a conversa. Uma vale depois
    de falar com a pessoa; a outra, antes.
    """
    monkeypatch.setenv(CHAVE, "false")
    monkeypatch.delenv("PANICO_AUTONOMO", raising=False)

    cfg = Settings(_env_file=None)

    assert cfg.triagem_previa_ativa is False
    assert cfg.panico_autonomo is False
