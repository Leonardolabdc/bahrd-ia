"""A tela de eventos de teste nasce desligada, e produção não pode ligá-la.

Ela é a única parte do sistema em que o destino de uma mensagem é escolhido por
uma pessoa, e não por um evento de veículo. Tudo o mais que a IA escreve nasce
de um alarme real; aqui nasce de um clique. Por isso a tela é a parte mais
travada do sistema, e não a menos.

O que um clique dispara, para calibrar o tamanho do risco: template pela Meta
para o celular escolhido, pelo número oficial **verificado** da Bahrd. No pânico
esse template diz "Acionamento do botão de pânico" e traz um botão que liga
para o 0800 da Central. Mandar isso para quem não pediu é alarme falso com a
credibilidade da empresa, e ainda gera ligação no 0800 de verdade.

A forma destas duas travas é copiada de `langfuse_com_conteudo` de propósito.
Decisão dessa natureza mora no código, à vista, e não numa variável de ambiente
que alguém esquece ligada ao promover o ambiente.
"""

from __future__ import annotations

import pytest

from central_ia.config import Settings

_SEM_TELA = ("PAINEL_TESTES_ATIVO",)


def _cfg(monkeypatch: pytest.MonkeyPatch, **extra: str) -> Settings:
    """Ambiente declarado, nunca herdado.

    O compose exporta o `.env` como variável real, então `_env_file=None` não
    basta: sem limpar, estes testes passariam ou falhariam conforme a máquina
    de quem roda.
    """
    monkeypatch.setenv("ORACLE_PASSWORD", "senha-oracle")
    monkeypatch.setenv("MYSQL_PASSWORD", "senha-mysql")
    for chave in _SEM_TELA:
        monkeypatch.delenv(chave, raising=False)
    for chave, valor in extra.items():
        monkeypatch.setenv(chave, valor)
    return Settings()


def test_nasce_desligada(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sem ninguém decidir nada, a tela não existe."""
    assert _cfg(monkeypatch).testes_pelo_painel is False


def test_ligar_em_desenvolvimento_funciona(monkeypatch: pytest.MonkeyPatch) -> None:
    """A trava é de produção, não de teimosia: em dev, ligar liga."""
    cfg = _cfg(monkeypatch, PAINEL_TESTES_ATIVO="true")

    assert cfg.em_producao is False
    assert cfg.testes_pelo_painel is True


@pytest.mark.parametrize("ambiente", ["hml", "prd-poc"])
def test_producao_vence_a_variavel(monkeypatch: pytest.MonkeyPatch, ambiente: str) -> None:
    """⛔ A asserção que importa. Não há valor de `.env` que ligue a tela lá.

    Homologação entra junto: é onde os números já podem ser de gente de
    verdade, e onde alguém liga "só para ver se funciona".
    """
    cfg = _cfg(monkeypatch, PAINEL_TESTES_ATIVO="true", APP_ENV=ambiente)

    assert cfg.painel_testes_ativo is True, "a variável foi lida"
    assert cfg.testes_pelo_painel is False, "e o ambiente venceu"


def test_a_tela_nao_tem_mais_lista_de_destinos() -> None:
    """⚠️ **Havia `PAINEL_NUMEROS_DE_TESTE`, e ela saiu em 03/09/2026.**

    A trava era boa contra o dígito trocado e ruim para o propósito da tela: a
    Central precisa testar com o celular de quem estiver na sala, e a lista
    obrigava a chamar o dev para cada número novo, que é justamente o que a tela
    existe para evitar. Decisão da operação, registrada aqui para ninguém
    reintroduzir a variável achando que ela sumiu por descuido.

    O que sobrou no lugar: validação de formato no servidor, o `PAINEL_TOKEN`,
    o teto diário e o 404 fora de desenvolvimento.
    """
    assert not hasattr(Settings(), "painel_numeros_de_teste")
    assert not hasattr(Settings(), "numeros_de_teste_do_painel")
