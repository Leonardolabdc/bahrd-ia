"""A amostra do painel não pode divergir da política.

Uma tela mostrando tipo de evento fora do escopo — ou pior, a IA "atendendo"
um pânico — é o tipo de erro que passa despercebido numa demonstração e vira
expectativa errada com o cliente. Estes testes fecham essa porta.
"""

from __future__ import annotations

import re

from central_ia.api import amostra
from central_ia.domain import eventos

ROTULOS_EM_ESCOPO = {t.rotulo for t in eventos.CATALOGO}


def _todos_os_itens() -> list:
    fila = amostra.fila()
    return [*fila.precisa_de_voce, *fila.ia_esta_fazendo]


def test_fila_so_tem_tipos_em_escopo() -> None:
    fora = {i.tipo_evento for i in _todos_os_itens()} - ROTULOS_EM_ESCOPO
    assert not fora, f"tipos fora do catálogo na amostra: {sorted(fora)}"


def test_ia_nunca_aparece_atendendo_panico() -> None:
    """Princípio 3: eventos críticos nunca vão para a IA."""
    em_atendimento = {i.tipo_evento for i in amostra.fila().ia_esta_fazendo}
    assert eventos.PANICO.rotulo not in em_atendimento


def test_panico_na_fila_humana_tem_leitura_e_nenhuma_conversa() -> None:
    """A IA lê o contexto e não fala com ninguém."""
    panicos = [
        i for i in amostra.fila().precisa_de_voce if i.tipo_evento == eventos.PANICO.rotulo
    ]
    assert panicos, "o pânico precisa aparecer na fila do operador"

    for item in panicos:
        assert item.leitura_ia, "sem leitura de contexto o operador começa do zero"
        assert item.roteiro == [], "roteiro implicaria a IA conduzindo o caso"
        assert item.falas == [], "pânico não tem conversa da IA"
        assert item.tem_ao_vivo is False

    detalhe = amostra.ocorrencia(panicos[0].ocorrencia_id)
    assert detalhe is not None
    assert detalhe.conversa == []


def test_sla_da_fila_bate_com_a_janela_do_catalogo() -> None:
    """O relógio na tela e a janela da política têm de ser o mesmo número."""
    por_rotulo = {t.rotulo: t for t in eventos.CATALOGO}
    for item in _todos_os_itens():
        assert item.sla_s == por_rotulo[item.tipo_evento].janela_s


def test_metricas_so_reportam_tipos_em_escopo() -> None:
    rotulos = {b.rotulo for b in amostra.metricas().volume_por_evento}
    assert rotulos <= ROTULOS_EM_ESCOPO


def test_ocorrencias_detalhadas_estao_em_escopo() -> None:
    for item in _todos_os_itens():
        if not item.tem_detalhe:
            continue
        detalhe = amostra.ocorrencia(item.ocorrencia_id)
        assert detalhe is not None, f"{item.ocorrencia_id} promete detalhe e não tem"
        assert detalhe.tipo_evento in ROTULOS_EM_ESCOPO


def test_toda_linha_da_fila_abre_alguma_coisa() -> None:
    """Numa POC, item que não abre é item que ninguém consegue avaliar.

    Cada linha precisa levar a algum lugar: o registro completo (`tem_detalhe`)
    ou a tela ao vivo (`tem_ao_vivo`). Uma linha sem nenhum dos dois só balança
    quando clicada, e quem está avaliando a POC conclui que está quebrada.
    """
    for item in _todos_os_itens():
        assert item.tem_detalhe or item.tem_ao_vivo, (
            f"{item.ocorrencia_id} ({item.tipo_evento}) não abre nada"
        )


def test_toda_linha_da_fila_tem_posicao_para_o_mapa() -> None:
    """A tela ao vivo lê a posição do item da fila, não da ocorrência.

    Sem isso, o mapa aparece nos casos abertos e some nos que estão em
    atendimento — e o operador conclui que a IA perdeu o veículo.
    """
    for item in _todos_os_itens():
        assert item.latitude is not None and item.longitude is not None, (
            f"{item.ocorrencia_id} ({item.tipo_evento}) entra na fila sem posição"
        )


def test_ocorrencia_com_mapa_tem_as_duas_coordenadas() -> None:
    """Meia coordenada não desenha nada — e pior, some sem explicação.

    Também trava a faixa: latitude fora de [-90, 90] ou longitude fora de
    [-180, 180] põe o pino em lugar nenhum, e ninguém repara olhando a tela.
    """
    for item in _todos_os_itens():
        detalhe = amostra.ocorrencia(item.ocorrencia_id)
        if detalhe is None:
            continue
        tem_lat = detalhe.latitude is not None
        tem_lon = detalhe.longitude is not None
        assert tem_lat == tem_lon, f"{item.ocorrencia_id}: coordenada pela metade"
        if tem_lat:
            assert -90 <= detalhe.latitude <= 90  # type: ignore[operator]
            assert -180 <= detalhe.longitude <= 180  # type: ignore[operator]


def test_data_da_fila_tem_ano() -> None:
    """A base da Bahrd tem registro antigo — data sem ano vira dúvida."""
    for item in amostra.fila().precisa_de_voce:
        assert item.dia and re.fullmatch(r"\d{2}/\d{2}/\d{4}", item.dia), (
            f"{item.ocorrencia_id}: data '{item.dia}' sem ano"
        )


# ───────────────────────────── Encerrados ─────────────────────────────


def test_encerrados_so_tem_tipos_em_escopo() -> None:
    fora = {e.tipo_evento for e in amostra.encerrados().itens} - ROTULOS_EM_ESCOPO
    assert not fora, f"tipos fora do catálogo entre os encerrados: {sorted(fora)}"


def test_totais_de_encerrados_batem_com_as_linhas() -> None:
    """O número no cabeçalho e a lista abaixo dele são a mesma fonte.

    Se divergirem, a contenção vira um número que ninguém consegue conferir —
    exatamente o que a tela existe para evitar.
    """
    dados = amostra.encerrados()
    assert dados.total_ia == sum(1 for e in dados.itens if e.encerrada_por == "ia")
    assert dados.total_operador == sum(1 for e in dados.itens if e.encerrada_por == "operador")
    assert dados.total_ia + dados.total_operador == len(dados.itens)


def test_encerrada_pela_ia_nunca_e_evento_inelegivel_sem_triagem() -> None:
    """Princípio 3 na tela de fechamento.

    Um evento que a política não libera para a IA só pode aparecer como
    "fechado pela IA" com um desfecho de triagem — nunca como atendimento.
    """
    por_rotulo = {t.rotulo: t for t in eventos.CATALOGO}
    for e in amostra.encerrados().itens:
        if e.encerrada_por != "ia":
            continue
        tipo = por_rotulo[e.tipo_evento]
        assert tipo.elegivel_ia, (
            f"{e.ocorrencia_id}: {e.tipo_evento} é inelegível e aparece fechado pela IA"
        )


def test_linha_de_encerrado_so_promete_detalhe_que_existe() -> None:
    """Clique que leva a 404 corrói a confiança na tela inteira."""
    for e in amostra.encerrados().itens:
        if e.tem_detalhe:
            assert amostra.ocorrencia(e.ocorrencia_id) is not None


def test_linha_e_detalhe_contam_a_mesma_coisa() -> None:
    """A lista é derivada do registro; se divergirem, a aba deixa de ser auditável."""
    for e in amostra.encerrados().itens:
        detalhe = amostra.ocorrencia(e.ocorrencia_id)
        assert detalhe is not None
        assert (detalhe.tipo_evento, detalhe.canal, detalhe.placa, detalhe.duracao) == (
            e.tipo_evento,
            e.canal,
            e.placa,
            e.duracao,
        )


def test_fechamento_de_humano_tem_nome_de_gente() -> None:
    """"Operador" é papel; quem responde por um fechamento é uma pessoa.

    Sem o nome na linha, auditar um fechamento humano vira uma caça ao log —
    e é justamente o fechamento humano que precisa ser localizável depois.
    """
    for e in amostra.encerrados().itens:
        assert e.responsavel.strip(), f"{e.ocorrencia_id} sem responsável"
        if e.encerrada_por == "ia":
            assert e.responsavel == "IA"
        else:
            assert e.responsavel.lower() not in {"operador", "humano", "ia"}
            assert " " in e.responsavel, "esperado nome e sobrenome"


def test_evento_critico_acima_do_limiar_nao_tem_conversa() -> None:
    """A trava central da política v2.0, verificada na tela.

    Acima do limiar a IA entrega o caso **sem ter falado com ninguém**. Uma
    ocorrência que mostrasse 94% de chance de ser real e uma conversa da IA
    estaria afirmando que ela ligou para alguém que podia estar sob ameaça.
    """
    for oc_id in ("OC-2026-08-11-000478",):
        detalhe = amostra.ocorrencia(oc_id)
        assert detalhe is not None
        assert detalhe.probabilidade_real is not None
        if detalhe.probabilidade_real >= eventos.LIMIAR_ESCALONAMENTO:
            assert detalhe.conversa == [], f"{oc_id}: acima do limiar e com conversa"


def test_caso_critico_entregue_ao_humano_traz_o_que_a_ia_fez() -> None:
    """Sem o handoff, quem assume refaz do zero e a triagem não economizou nada."""
    detalhe = amostra.ocorrencia("OC-2026-08-11-000478")
    assert detalhe is not None
    assert detalhe.handoff, "caso crítico sem histórico do que a IA apurou"
    assert detalhe.probabilidade_real is not None


def test_desfecho_de_panico_esta_na_lista_branca() -> None:
    """A IA e o operador fecham; a lista branca vale para os dois na tela."""
    for e in amostra.encerrados().itens:
        if e.tipo_evento != eventos.PANICO.rotulo:
            continue
        assert eventos.desfecho_permitido("PANICO", e.desfecho), (
            f"{e.ocorrencia_id}: desfecho '{e.desfecho}' fora da lista branca"
        )


# ──────────────────────── Reincidência / recall ────────────────────────


def test_recall_segue_o_criterio_declarado() -> None:
    """A marcação é aritmética, não julgamento — e tem de ser reproduzível.

    Se a regra e a marcação divergirem, a manutenção passa a inspecionar
    equipamento por um número que a tela inventou.
    """
    for e in amostra.reincidencia():
        esperado = (
            e.ocorrencias_90d >= amostra.MINIMO_OCORRENCIAS
            and e.confirmados_sem_causa >= amostra.MINIMO_SEM_CAUSA
        )
        assert e.candidato_a_recall is esperado, f"{e.placa} destoa do critério"


def test_sem_causa_nunca_passa_do_total() -> None:
    for e in amostra.reincidencia():
        assert 0 <= e.confirmados_sem_causa <= e.ocorrencias_90d


def test_reincidencia_so_conta_tipos_em_escopo() -> None:
    fora = {e.tipo_evento for e in amostra.reincidencia()} - ROTULOS_EM_ESCOPO
    assert not fora, f"tipos fora do catálogo na reincidência: {sorted(fora)}"


def test_so_tem_destino_o_vital_que_leva_a_algum_lugar() -> None:
    """Número com cara de clicável e sem destino ensina a desconfiar da tela.

    Latência e contenção não têm detalhamento — e por isso não podem receber
    `destino`, senão o painel promete um clique que não existe.
    """
    com_destino = {v.rotulo: v.destino for v in amostra.metricas().vitais if v.destino}
    assert com_destino == {"Encerradas": "encerrados", "Para inspeção": "recall"}


def test_vital_de_encerradas_bate_com_a_lista() -> None:
    """O agregado da Visão Geral e a aba Encerrados não podem divergir."""
    dados = amostra.encerrados()
    vitais = {v.rotulo: v for v in amostra.metricas().vitais}
    assert vitais["Encerradas"].valor == str(dados.total_ia + dados.total_operador)
    assert vitais["Para inspeção"].valor == str(
        sum(1 for e in amostra.reincidencia() if e.candidato_a_recall)
    )
