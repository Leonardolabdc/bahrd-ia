"""A chave que faz a IA encerrar tudo, sem passar para um operador.

Nesta fase não há operador para receber, não há cliente real e não há o dado
interno da Bahrd para cruzar — escalar é entregar o caso a ninguém, e a fila
humana enche de ocorrências que ninguém vai olhar.

O que estes testes guardam é a parte que **não** pode mudar junto: o
julgamento da IA continua o mesmo, o motivo vai para o registro, e a lista
branca continua fechada. A chave muda o destino do caso, não a régua.
"""

from __future__ import annotations

from central_ia.api.rotas.whatsapp import _encaminhar
from central_ia.config import Settings
from central_ia.domain import eventos
from central_ia.orchestration.sessao_whatsapp import Sessoes

TELEFONE = "whatsapp:+5541999999999"
DADOS = {"placa": "GHI7J89", "interlocutor": "Bruno Ramos"}


def _cfg(escalonamento: bool) -> Settings:
    return Settings(
        oracle_password="x",
        mysql_password="x",
        escalonamento_humano_ativo=escalonamento,
    )


def _sessao():
    return Sessoes().abrir(TELEFONE, eventos.REMOCAO_BATERIA, "TEXTO", DADOS)


def test_sem_operador_a_ia_encerra_e_guarda_o_motivo() -> None:
    """Encerrar não é dizer que estava tudo bem.

    O desfecho gravado é o próprio motivo do escalonamento — quem ler a lista
    de encerrados vê "reboque sem autorização", não "resolvido".
    """
    s = _sessao()
    frase = _encaminhar(_cfg(False), s, "reboque_sem_autorizacao", "Gestor não confirmou.")

    assert s.encerrada
    assert s.escalada is False
    assert s.desfecho == "reboque_sem_autorizacao"
    assert "colega" not in frase.lower(), "não promete transferência que não existe"


def test_com_operador_o_caso_vai_para_a_fila_humana() -> None:
    """A chave em `True` devolve o comportamento antigo, sem tocar em prompt."""
    s = _sessao()
    frase = _encaminhar(_cfg(True), s, "reboque_sem_autorizacao", "Gestor não confirmou.")

    assert s.encerrada
    assert s.escalada is True
    assert s.desfecho is None, "sem operador não há desfecho: o caso está em aberto"
    assert "colega" in frase.lower()


def test_o_motivo_fica_na_trilha_nos_dois_modos() -> None:
    """A auditoria não pode depender da fase do projeto.

    O que a IA concluiu é o mesmo nos dois casos; só o destino muda. Se o
    motivo sumisse no modo sem operador, ninguém saberia depois quais casos
    teriam ido para uma pessoa.
    """
    for ativo in (True, False):
        s = _sessao()
        _encaminhar(_cfg(ativo), s, "motivo_x", "Explicação que precisa sobreviver.")
        trilha = " ".join(p.descricao for p in s.trilha)
        assert "Explicação que precisa sobreviver." in trilha


def test_modo_sem_operador_deixa_marcado_na_trilha() -> None:
    """Quem auditar meses depois precisa saber que não havia operador."""
    s = _sessao()
    _encaminhar(_cfg(False), s, "motivo_x", "qualquer coisa")
    trilha = " ".join(p.descricao for p in s.trilha).lower()
    assert "sem operador" in trilha


def test_a_frase_final_nunca_promete_transferencia_sem_operador() -> None:
    """Prometer "vou te passar pra um colega" sem colega é mentir no fim.

    Aconteceu num teste real: a IA encerrou o caso corretamente e despediu-se
    dizendo que ia transferir. A pessoa fica esperando um retorno que não vem.
    """
    from central_ia.agent.atendimento_real import despedida

    sem = despedida("Bruno Ramos", com_operador=False)
    assert "colega" not in sem.lower()
    assert "instante" not in sem.lower()
    assert "Bruno" in sem, "chamar pelo nome é o mínimo numa despedida"

    com = despedida("Bruno Ramos", com_operador=True)
    assert "colega" in com.lower()


def test_despedida_funciona_sem_nome() -> None:
    """Interlocutor desconhecido existe — e a frase não pode sair quebrada."""
    frase = despedida_sem_nome = __import__(
        "central_ia.agent.atendimento_real", fromlist=["despedida"]
    ).despedida(None, com_operador=False)
    assert "{" not in frase and "}" not in frase
    assert frase.strip()
    assert despedida_sem_nome == frase


def test_a_chave_nao_afrouxa_a_lista_branca() -> None:
    """Desfecho inventado pelo modelo continua recusado nos dois modos.

    A chave muda para onde o caso vai. Se ela também abrisse a lista branca,
    viraria porta lateral para fechar com qualquer coisa.
    """
    assert not eventos.desfecho_permitido("REMOCAO_BATERIA", "tudo_certo_por_aqui")
    assert not eventos.desfecho_permitido("PANICO", "resolvido")
