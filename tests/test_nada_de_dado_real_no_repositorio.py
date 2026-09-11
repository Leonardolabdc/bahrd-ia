"""O repositório vai para o GitHub da Bahrd. O que está aqui, sai daqui.

Escrito em 27/08/2026, quando o Leonardo recebeu acesso ao GitHub da empresa e
pedimos uma auditoria antes de subir. O resultado foi bom — nenhuma chave de
API jamais foi commitada, o `.env` nunca entrou no histórico — com **uma**
exceção: o celular pessoal dele estava em doze arquivos, em docstring e em
teste, porque foi o número usado nos primeiros testes reais.

Não é credencial e não abre nada. É dado pessoal num repositório de empresa,
que é outro tipo de problema e não menor: sai do controle de quem o cedeu, fica
no histórico do Git para sempre, e quem clonar em dois anos não vai saber de
quem é.

Estes testes valem por uma revisão que ninguém vai lembrar de fazer.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

#: A raiz do repositorio, achada a partir DESTE arquivo.
#:
#: Nao usa o diretorio de trabalho de proposito: a suite roda dentro do
#: conteiner, onde o cwd e `/app` e nem todo arquivo da raiz esta montado.
RAIZ_DO_REPO = Path(__file__).resolve().parents[1]
RAIZ = RAIZ_DO_REPO / "src"
TESTES = RAIZ_DO_REPO / "tests"


def _exige(nome: str) -> Path:
    """O arquivo da raiz, ou pula dizendo por que.

    A imagem do conteiner copia `src`, `tests`, `prompts` e `infra`, e mais
    nada — `.gitignore` e `.env.example` ficam de fora. Estes dois testes sao
    para rodar num checkout completo, que e o caso do CI e da maquina de quem
    desenvolve. Pular aqui e honesto; fingir que passou nao seria.
    """
    caminho = RAIZ_DO_REPO / nome
    if not caminho.exists():
        pytest.skip(f"{nome} nao esta neste ambiente (a imagem do conteiner nao o copia)")
    return caminho

#: Celular brasileiro em qualquer grafia: com ou sem `+`, com ou sem o nono.
_CELULAR = re.compile(r"\b55\d{2}9?\d{8}\b")

#: Quantos dígitos distintos bastam para o número parecer de alguém.
#:
#: **Uma regra, e não uma lista de permitidos.** Lista precisa ser atualizada
#: por quem acrescenta um número, e quem esquece de atualizar é justamente quem
#: colou o número errado. A regra se aplica sozinha.
#:
#: Ela funciona porque número inventado é feito de repetição — `99999-9999`,
#: `8888-7777`, `3322-1100` — e número de gente não é. Medido nos 14 fictícios
#: que já existiam no repositório e nos 3 reais que passaram por aqui:
#:
#:     fictícios   1 a 4 dígitos distintos
#:     reais       5 a 6
#:
#: O corte em 5 é onde a separação está, com folga dos dois lados.
_DISTINTOS_DEMAIS = 5


def _parece_de_alguem(numero: str) -> bool:
    """Conta os dígitos distintos da parte do assinante, depois de `55` e do DDD.

    `…99999-9999` não, `…98423-8872` sim. O exemplo positivo fica assim, pela
    metade, porque escrevê-lo inteiro colocaria neste arquivo exatamente o tipo
    de dado que ele existe para manter fora.
    """
    return len(set(numero[4:])) >= _DISTINTOS_DEMAIS


def test_nenhum_celular_real_no_codigo_nem_nos_testes() -> None:
    """⚠️ Número de gente de verdade não entra em repositório de empresa.

    Se este teste falhar, a pergunta não é "como faço passar" — é **de quem é
    esse número**. Troque por um com dígitos repetidos, que qualquer leitor
    reconhece como inventado à primeira vista.

    Um número plausível escrito à toa é pior do que um óbvio: ele *pode* ser de
    alguém, e ninguém vai conferir depois de commitado.
    """
    achados: list[str] = []
    for pasta in (RAIZ, TESTES):
        for caminho in pasta.rglob("*.py"):
            texto = caminho.read_text(encoding="utf-8")
            for numero in sorted(set(_CELULAR.findall(texto))):
                if _parece_de_alguem(numero):
                    relativo = caminho.relative_to(RAIZ_DO_REPO)
                    achados.append(f"{relativo}: {numero}")

    assert not achados, (
        "número com cara de ser de alguém de verdade:\n  " + "\n  ".join(achados)
    )


def test_a_regra_separa_o_inventado_do_real() -> None:
    """O guarda do guarda: se a regra parar de separar, ela para de proteger.

    **Os exemplos de "alta diversidade" aqui são sequências, não números de
    ninguém** — e essa escolha custou uma execução para eu aprender. A primeira
    versão deste teste trazia os três celulares reais que passaram pelo projeto,
    para provar que a regra os pegava. O teste de cima os encontrou **dentro
    deste arquivo** e falhou.

    Foi o guarda pegando quem o escreveu, e está certo: o jeito de demonstrar
    que a regra funciona não pode ser escrever no repositório justamente o que
    ela existe para manter fora.
    """
    # Montados em pedaços de propósito: assim o número completo não existe como
    # texto neste arquivo, e o teste de cima não se pega a si mesmo. Escrever
    # qualquer um deles inteiro faria o guarda falhar sobre o próprio exemplo,
    # e falhou duas vezes enquanto eu escrevia isto.
    def _monta(assinante: str) -> str:
        return "55" + "41" + assinante

    for parece_gente in (_monta("912345678"), _monta("12345678"), _monta("987654321")):
        assert _parece_de_alguem(parece_gente), f"{parece_gente} deveria ser pego"

    for inventado in ("5541999999999", "554188887777", "554133221100", "5511988887777"):
        assert not _parece_de_alguem(inventado), f"{inventado} não deveria ser pego"


def test_o_env_de_exemplo_nao_traz_credencial_de_verdade() -> None:
    """`.env.example` é versionado. Ele documenta as chaves, nunca os valores.

    As senhas de dev que sobram ali (`CentralIA_Dev1`, `MySQLRootDev1`) são de
    contêiner local e existem para o `docker compose up` funcionar sem edição.
    Nenhuma delas abre nada fora desta máquina — e o teste garante que nenhuma
    credencial **de fornecedor** se junte a elas por distração.
    """
    exemplo = _exige(".env.example").read_text(encoding="utf-8")

    #: Chaves que, se preenchidas, custam dinheiro ou dão acesso de verdade.
    de_fornecedor = (
        "ANTHROPIC_API_KEY",
        "OPENROUTER_API_KEY",
        "DEEPGRAM_API_KEY",
        "ELEVENLABS_API_KEY",
        "TWILIO_AUTH_TOKEN",
        "LANGFUSE_SECRET_KEY",
        "META_ACCESS_TOKEN",
        "META_APP_SECRET",
        "PAINEL_TOKEN",
    )

    preenchidas = [
        linha.split("=", 1)[0]
        for linha in exemplo.splitlines()
        if "=" in linha
        and linha.split("=", 1)[0].strip() in de_fornecedor
        and linha.split("=", 1)[1].strip()
    ]

    assert not preenchidas, f"credencial de fornecedor preenchida no exemplo: {preenchidas}"


def test_o_gitignore_cobre_o_que_nao_pode_subir() -> None:
    """A primeira linha de defesa, e a única que age sozinha.

    Os testes acima pegam o que já entrou; este confere que a porta está
    fechada.

    ⚠️ É `docs/*` com asterisco, e não `docs/`. A diferença não é estilo: dentro
    de uma pasta ignorada o Git **não entra** para avaliar exceção, então um
    `!docs/07-seguranca.md` seria descartado junto e os links do README voltariam
    a quebrar. Com `docs/*` o conteúdo é ignorado e a pasta não.

    Sobem os documentos numerados que o README referencia. Não sobem as três
    subpastas: `arquivo/` (documentos superados), `interno/` (prints de conversas
    dos gestores) e `exemplos/` (planilha com dado real de cliente).
    """
    regras = {
        linha.strip()
        for linha in _exige(".gitignore").read_text(encoding="utf-8").splitlines()
        if linha.strip() and not linha.startswith("#")
    }

    for obrigatoria in (".env", "docs/*", "*.pem", "*.key"):
        assert obrigatoria in regras, f"o .gitignore precisa cobrir {obrigatoria}"

    # O que sobe de `docs/` é lista explícita, nunca padrão amplo.
    excecoes = {r for r in regras if r.startswith("!docs/")}
    assert excecoes, "nenhum documento liberado — os links do README quebrariam"
    for excecao in excecoes:
        assert not any(
            excecao.startswith(f"!docs/{p}/") for p in ("arquivo", "interno", "exemplos")
        ), f"{excecao} libera material interno"
