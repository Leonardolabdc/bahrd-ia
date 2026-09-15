"""O ramo TLS do MySQL, que nunca tinha rodado.

Este arquivo existe por causa de um defeito específico, e vale registrar como
ele passou despercebido.

O módulo `persistence/mysql.py` afirmava, no próprio cabeçalho, que *"TLS já é
exercitado em local para que `REQUIRED` na Fase 2 não seja a primeira vez que o
caminho roda"*. A frase descrevia uma intenção, não um fato: o
`docker-compose.yml` usa `MYSQL_SSL_MODE=DISABLED`, então `_connect_args`
devolvia `{}` em toda execução local e em todo teste. O ramo `REQUIRED` nunca
foi executado até o primeiro deploy contra o MySQL HeatWave — e quebrou na hora.

O erro foi `AttributeError: 'dict' object has no attribute 'wrap_bio'`, que não
menciona TLS nem MySQL, e que chegou até a sonda de prontidão apenas como
"dependência indisponível".

A lição: **um comentário afirmando que algo é testado não testa nada.** Os
testes abaixo fazem a afirmação do cabeçalho passar a ser verdadeira.
"""

from __future__ import annotations

import ssl

import pytest

from central_ia.config import Settings
from central_ia.persistence.mysql import _connect_args


def _cfg(modo: str) -> Settings:
    return Settings(mysql_ssl_mode=modo)


def test_desligado_nao_passa_parametro_de_ssl() -> None:
    """Em desenvolvimento não há TLS, e o dicionário sai vazio."""
    assert _connect_args(_cfg("DISABLED")) == {}


@pytest.mark.parametrize("modo", ["REQUIRED", "PREFERRED"])
def test_ligado_devolve_um_sslcontext_de_verdade(modo: str) -> None:
    """O defeito exato: um dicionário aqui quebra o driver em produção.

    O aiomysql antigo aceitava qualquer dicionário não vazio como "ligue o
    TLS". O atual passa o valor direto ao protocolo, que chama `wrap_bio` nele
    — método que só existe num `SSLContext`.
    """
    args = _connect_args(_cfg(modo))

    assert "ssl" in args, f"modo {modo} precisa pedir TLS"
    assert isinstance(args["ssl"], ssl.SSLContext), (
        f"modo {modo} devolveu {type(args['ssl']).__name__}; "
        "um dicionario aqui levanta AttributeError 'wrap_bio' em producao"
    )
    # A prova direta: é isto que o driver chama, e é o que faltava.
    assert hasattr(args["ssl"], "wrap_bio")


@pytest.mark.parametrize("modo", ["REQUIRED", "PREFERRED"])
def test_nao_verifica_a_identidade_do_servidor(modo: str) -> None:
    """Deliberado, e não descuido.

    `REQUIRED`, no MySQL, significa "exija criptografia" — não "verifique quem
    é o servidor". Verificar é `VERIFY_CA` e `VERIFY_IDENTITY`, que são outros
    modos e não estão em uso aqui.

    E não haveria como verificar: o HeatWave é alcançado por endereço privado,
    e certificado nenhum casa com um IP. O que protege a identidade do servidor
    neste desenho é a sub-rede privada — está registrado no
    [ADR-002](../docs/adr/0002-plataforma-de-publicacao.md).

    Se algum dia o acesso passar a ser por nome, este teste deve falhar e ser
    reescrito, e não apagado: a mudança de modelo de confiança merece revisão.
    """
    contexto = _connect_args(_cfg(modo))["ssl"]

    assert contexto.check_hostname is False
    assert contexto.verify_mode == ssl.CERT_NONE
