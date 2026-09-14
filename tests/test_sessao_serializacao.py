"""A sessão sobrevive a um reinício do processo — ida e volta, sem perder nada.

Roda sem Redis: o que se testa aqui é a **serialização**, que é pura. O depósito
tem teste próprio.

O teste mais importante deste arquivo é `test_todo_campo_da_sessao_e_gravado`.
Ele não exercita comportamento: compara a lista de campos do dataclass com o
payload gravado e reprova quando alguém acrescenta um campo e esquece de
serializá-lo. Esse esquecimento não quebra nada visivelmente — a sessão volta do
reinício com o campo no padrão, e o defeito aparece como comportamento estranho
muito depois, longe da causa.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime, timedelta

import pytest

from central_ia.domain import eventos
from central_ia.orchestration.sessao_whatsapp import (
    Fala,
    PassoDaTrilha,
    Sessao,
    Sessoes,
)
from central_ia.ports.llm import Mensagem

TELEFONE = "whatsapp:+5511999999999"
DADOS = {
    "placa": "XYZ4E56",
    "interlocutor": "Marcos Pereira",
    "posição": "Rodovia Régis Bittencourt, Curitiba - PR",
}


def _sessao_cheia() -> Sessao:
    """Uma sessão com **todos** os campos fora do padrão.

    De propósito: uma sessão recém-aberta tem quase tudo no valor padrão, e um
    teste de ida e volta feito com ela passaria mesmo se metade dos campos
    fosse descartada na gravação.
    """
    agora = datetime.now(UTC)
    return Sessao(
        ocorrencia_id="ocr-123",
        telefone=TELEFONE,
        tipo=eventos.PANICO,
        canal="whatsapp",
        dados=dict(DADOS),
        origem="teste",
        modelo="claude-sonnet-5",
        latitude=-25.4284,
        longitude=-49.2733,
        endereco="Rodovia Régis Bittencourt, km 12",
        historico=[
            Mensagem(papel="user", conteudo="estou bem"),
            Mensagem(papel="assistant", conteudo="que bom"),
        ],
        turnos_ia=3,
        custo_usd=0.0412,
        encerrada=True,
        motivo_encerramento="cliente confirmou",
        desfecho="alarme_falso",
        escalada=True,
        probabilidade_real=42,
        triagem_autoriza_encerrar=True,
        houve_resposta=True,
        retomadas=2,
        aguardando=True,
        tentativas_de_injecao=1,
        causa_escolhida="manutencao",
        pediu_ajuda=True,
        nossas_mensagens={"wamid.B", "wamid.A"},
        teto_de_retomadas=4,
        toque_adiado="pergunta_causa",
        toque_ja_na_tela="saudacao",
        handoff=["operador pediu assumir"],
        criada_em=agora - timedelta(minutes=30),
        ultima_em=agora - timedelta(minutes=2),
        falas=[
            Fala(quem="ia", texto="tudo bem?", momento=agora, tipo="template",
                 botoes=["Sim", "Não"]),
            Fala(quem="cliente", texto="sim", momento=agora, audio=True,
                 transcrito=True, duracao_s=3.5),
        ],
        trilha=[PassoDaTrilha(momento=agora, ator="ia", descricao="abriu")],
        desativada_ate=agora + timedelta(hours=2),
        desativada=True,
    )


def test_todo_campo_da_sessao_e_gravado() -> None:
    """Nenhum campo do dataclass pode ficar de fora do payload.

    Quando este teste falhar, provavelmente não há defeito na serialização: há
    um campo novo em `Sessao`, e ele precisa entrar em `para_dicionario` **e**
    em `de_dicionario`. Os dois, não um.
    """
    campos = {f.name for f in dataclasses.fields(Sessao)}
    gravados = set(_sessao_cheia().para_dicionario())

    faltando = campos - gravados
    assert not faltando, (
        f"campos de Sessao que nao sao gravados: {sorted(faltando)} — "
        "acrescente em para_dicionario() E em de_dicionario()"
    )

    sobrando = gravados - campos
    assert not sobrando, f"payload grava chave que nao existe em Sessao: {sorted(sobrando)}"


def test_ida_e_volta_preserva_a_sessao() -> None:
    original = _sessao_cheia()
    voltou = Sessao.de_dicionario(original.para_dicionario())

    for campo in dataclasses.fields(Sessao):
        antes = getattr(original, campo.name)
        depois = getattr(voltou, campo.name)
        assert antes == depois, f"campo '{campo.name}': {antes!r} virou {depois!r}"


def test_payload_e_json_de_verdade() -> None:
    """`set` e `datetime` não são JSON, e é onde a gravação costuma quebrar.

    Sem esta garantia o defeito só apareceria no Redis, em produção, no primeiro
    `json.dumps` — e não aqui.
    """
    bruto = json.dumps(_sessao_cheia().para_dicionario())
    assert Sessao.de_dicionario(json.loads(bruto)).ocorrencia_id == "ocr-123"


def test_momento_sem_fuso_nao_derruba_a_sessao() -> None:
    """Data gravada sem fuso precisa voltar com fuso.

    Comparar *naive* com *aware* levanta `TypeError`, e aqui isso aconteceria
    dentro de `viva` — ou seja, ao decidir se uma conversa continua. O erro não
    apareceria na gravação, e sim no primeiro acesso depois do reinício.
    """
    d = _sessao_cheia().para_dicionario()
    d["criada_em"] = datetime.now(UTC).replace(tzinfo=None).isoformat()

    sessao = Sessao.de_dicionario(d)
    assert sessao.criada_em.tzinfo is not None
    assert sessao.viva in (True, False)  # não levanta


def test_tipo_de_evento_volta_do_catalogo_e_nao_do_payload() -> None:
    """A sessão guarda o código, não uma cópia do catálogo.

    Se gravasse o objeto inteiro, uma correção de política nunca alcançaria as
    conversas já abertas: cada sessão carregaria a versão congelada do dia em
    que foi aberta.
    """
    d = _sessao_cheia().para_dicionario()
    assert d["tipo"] == eventos.PANICO.codigo
    assert isinstance(d["tipo"], str)
    assert Sessao.de_dicionario(d).tipo is eventos.PANICO


def test_tipo_desconhecido_e_recusado_com_erro_claro() -> None:
    """Um código que saiu do catálogo não pode virar sessão silenciosamente."""
    d = _sessao_cheia().para_dicionario()
    d["tipo"] = "EVENTO_QUE_NAO_EXISTE_MAIS"

    with pytest.raises(ValueError, match="tipo de evento desconhecido"):
        Sessao.de_dicionario(d)


def test_payload_e_estavel_entre_gravacoes() -> None:
    """Gravar duas vezes a mesma sessão precisa gerar os mesmos bytes.

    `nossas_mensagens` é um `set`, e a ordem de iteração de um set não é
    garantida entre processos. Sem ordenar, duas gravações idênticas produziriam
    payloads diferentes e qualquer comparação viraria ruído.
    """
    s = _sessao_cheia()
    assert json.dumps(s.para_dicionario()) == json.dumps(s.para_dicionario())
    assert s.para_dicionario()["nossas_mensagens"] == ["wamid.A", "wamid.B"]


def test_sessao_recem_aberta_tambem_faz_ida_e_volta() -> None:
    """O caminho comum, com quase tudo no padrão."""
    sessoes = Sessoes()
    aberta = sessoes.abrir(TELEFONE, eventos.REMOCAO_BATERIA, "whatsapp", DADOS)

    voltou = Sessao.de_dicionario(aberta.para_dicionario())
    assert voltou.ocorrencia_id == aberta.ocorrencia_id
    assert voltou.tipo is aberta.tipo
    assert voltou.viva
