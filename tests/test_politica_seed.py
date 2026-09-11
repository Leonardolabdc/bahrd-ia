"""O catálogo em código e a semente da política no Oracle não podem divergir.

São duas cópias da mesma decisão, em linguagens diferentes: o motor de
políticas lê da tabela, e a apresentação e os testes leem do catálogo. Se
alguém adicionar um tipo em um lado e esquecer o outro, o efeito é um evento
que a tela mostra e o motor ignora — ou pior, o contrário.

Este teste não abre conexão: lê o arquivo de migração como texto. Roda em
milissegundos e pega o erro antes de qualquer banco existir.
"""

from __future__ import annotations

import re
from pathlib import Path

from central_ia.domain import eventos

#: Sempre a semente da versão vigente. Ao subir a política, este apontamento
#: muda junto — e as migrações antigas ficam como estão, porque são o registro
#: de qual regra produziu cada atendimento.
VERSAO = eventos.POLITICA_VERSAO
SEMENTE = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "oracle"
    / "006_politica_evento_v2_0.sql"
)


def _sql() -> str:
    return SEMENTE.read_text(encoding="utf-8")


def _linhas_inseridas() -> list[tuple[str, str, str]]:
    """Extrai (tipo_evento, criticidade, elegivel_ia) de cada INSERT."""
    padrao = re.compile(
        rf"'{re.escape(VERSAO)}',\s*'([A-Z0-9_]+)',\s*'([A-Z]+)',\s*'([SN])'",
        re.MULTILINE,
    )
    return padrao.findall(_sql())


def test_semente_cobre_todo_o_catalogo() -> None:
    na_semente = {tipo for tipo, _, _ in _linhas_inseridas()}
    no_catalogo = {t.codigo for t in eventos.CATALOGO}

    assert na_semente == no_catalogo, (
        f"faltando na semente: {sorted(no_catalogo - na_semente)} · "
        f"sobrando na semente: {sorted(na_semente - no_catalogo)}"
    )


def test_criticidade_e_elegibilidade_batem() -> None:
    por_codigo = {t.codigo: t for t in eventos.CATALOGO}

    for codigo, criticidade, elegivel in _linhas_inseridas():
        tipo = por_codigo[codigo]
        assert criticidade == tipo.criticidade, f"{codigo}: criticidade divergente"
        assert (elegivel == "S") == tipo.elegivel_ia, f"{codigo}: elegibilidade divergente"


def _blocos() -> list[tuple[str, str]]:
    """(codigo, bloco SQL) de cada INSERT da versão vigente."""
    saida = []
    for bloco in _sql().split("INSERT INTO politica_evento")[1:]:
        achado = re.search(rf"'{re.escape(VERSAO)}',\s*'([A-Z0-9_]+)'", bloco)
        assert achado is not None
        saida.append((achado.group(1), bloco))
    return saida


def test_lista_branca_do_sql_bate_com_o_catalogo() -> None:
    """Lista vazia é a trava: o motor recusa desfecho fora da lista branca.

    Vale nos dois sentidos. Inelegível com desfecho no SQL abriria uma porta
    que o código fechou; elegível com lista vazia no código e cheia no SQL
    deixaria o motor fechar o que o catálogo proíbe.
    """
    for codigo, bloco in _blocos():
        tipo = eventos.por_codigo(codigo)
        assert tipo is not None
        vazia_no_sql = "'[]'" in bloco
        vazia_no_codigo = not tipo.desfechos_permitidos
        assert vazia_no_sql == vazia_no_codigo, f"{codigo}: lista branca divergente"


def test_triagem_previa_esta_registrada_na_politica() -> None:
    """O limiar precisa estar no registro, não só no código.

    É o número que explica, meses depois, por que aquele caso foi para o
    humano. Fora da política ele vira folclore.
    """
    for codigo, bloco in _blocos():
        tipo = eventos.por_codigo(codigo)
        assert tipo is not None
        if tipo.exige_triagem_previa:
            assert '"exige_triagem_previa": true' in bloco, f"{codigo}: falta a marca no SQL"
            assert (
                f'"limiar_escalonamento": {eventos.LIMIAR_ESCALONAMENTO}' in bloco
            ), f"{codigo}: limiar ausente ou divergente no SQL"


def test_elegivel_tem_playbook_no_sql() -> None:
    for codigo, bloco in _blocos():
        tipo = eventos.por_codigo(codigo)
        assert tipo is not None
        if tipo.elegivel_ia:
            assert tipo.playbook and tipo.playbook in bloco, f"{codigo}: playbook divergente"


def test_versao_anterior_e_encerrada_nao_apagada() -> None:
    """A versão que produziu cada atendimento tem de continuar reconstruível."""
    sql = _sql()
    assert "UPDATE politica_evento" in sql
    assert "ativo = 'N'" in sql
    assert "DELETE FROM politica_evento" not in sql
