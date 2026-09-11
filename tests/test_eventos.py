"""Catálogo de tipos de evento — as regras que não podem falhar.

Roda sem banco, sem rede e sem LLM: é o ponto do `domain/` ser puro.
"""

from __future__ import annotations

import pytest

from central_ia.domain import eventos


def test_escopo_e_exatamente_o_catalogo_da_link() -> None:
    """Trava explícita de escopo.

    Se alguém adicionar um tipo sem passar pela decisão de produto, o teste
    quebra aqui — e não numa ligação com um cliente.
    """
    assert [t.codigo for t in eventos.CATALOGO] == [
        "REMOCAO_BATERIA",
        "MOVIMENTO_SEM_IGNICAO",
        "VELOCIDADE_EXCEDIDA",
        "ULTRAPASSOU_LIMITE_VELOCIDADE",
        "VELOCIDADE_EXCEDIDA_CERCA_POLIGONO",
        "PANICO",
        "ROUBO_ATIVO_MOVIMENTO",
        "ENTRADA_2_ACIONADA",
        "ERRO_BATERIA_BACKUP",
        "ENTROU_NA_CERCA",
        "VOLTOU_CERCA_POLIGONO",
    ]


def test_rotulos_sao_os_do_sistema_da_link() -> None:
    """O webhook chega com o rótulo deles; a busca por rótulo tem de funcionar."""
    assert eventos.por_rotulo("Erro na bateria backup") is eventos.ERRO_BATERIA_BACKUP
    assert eventos.por_rotulo("Voltou à Cerca de Polígono") is eventos.VOLTOU_CERCA_POLIGONO
    assert (
        eventos.por_rotulo("ATENÇÃO: VEÍCULO COM ROUBO ATIVO SE MOVIMENTOU!")
        is eventos.ROUBO_ATIVO_MOVIMENTO
    )
    assert eventos.por_rotulo("Evento que a Bahrd não tem") is None


def test_roubo_ativo_nunca_pode_ser_fechado_pela_ia() -> None:
    """Elegível como todo o resto — mas sem nenhuma porta de saída.

    Política v2.0: o que barra a IA é a evidência, não o tipo. Na prática este
    evento quase nunca chega ao contato, porque o veículo já está marcado como
    roubado e a triagem entra alta. A lista branca vazia é o cinto de segurança
    embaixo disso: mesmo que a triagem errasse, a IA não teria com o que fechar.
    """
    assert eventos.elegivel_para_ia("ROUBO_ATIVO_MOVIMENTO") is True
    assert eventos.ROUBO_ATIVO_MOVIMENTO.exige_triagem_previa is True
    assert eventos.ROUBO_ATIVO_MOVIMENTO.desfechos_permitidos == ()
    assert eventos.desfecho_permitido("ROUBO_ATIVO_MOVIMENTO", "qualquer_coisa") is False


def test_eventos_com_pendencia_nao_sao_elegiveis() -> None:
    """Enquanto falta informação da Bahrd, a IA não conduz.

    Vale inclusive para os três de velocidade — eles são elegíveis porque têm
    playbook, e a pendência ali é de desambiguação, não de autorização.
    """
    sem_playbook = [t for t in eventos.CATALOGO if t.playbook is None]
    assert all(not t.elegivel_ia for t in sem_playbook)
    assert all(t.motivo_inelegibilidade for t in sem_playbook)


def test_eventos_de_velocidade_deduplicam_entre_si() -> None:
    """Um único excesso pode disparar mais de um rótulo.

    Três contatos com o mesmo motorista pelo mesmo fato é fadiga de alerta — o
    jeito mais rápido de a central perder credibilidade com quem está na estrada.
    """
    assert eventos.mesmo_grupo_de_deduplicacao(
        "VELOCIDADE_EXCEDIDA", "ULTRAPASSOU_LIMITE_VELOCIDADE"
    )
    assert eventos.mesmo_grupo_de_deduplicacao(
        "VELOCIDADE_EXCEDIDA", "VELOCIDADE_EXCEDIDA_CERCA_POLIGONO"
    )
    assert not eventos.mesmo_grupo_de_deduplicacao("VELOCIDADE_EXCEDIDA", "REMOCAO_BATERIA")


def test_pendencias_com_a_link_estao_registradas() -> None:
    """As perguntas em aberto ficam no código, não se perdem num documento."""
    pendentes = {rotulo for rotulo, _ in eventos.pendencias_com_a_link()}
    assert "Entrada 2 acionada" in pendentes
    assert "Entrou na cerca" in pendentes
    assert "Voltou à Cerca de Polígono" in pendentes
    assert "Erro na bateria backup" in pendentes


def test_panico_e_elegivel_mas_so_depois_da_triagem() -> None:
    """As duas coisas ao mesmo tempo, e são diferentes.

    Elegível: a IA trata. `exige_triagem_previa`: ela não abre a boca antes de
    olhar os dados. Confundir as duas é como um pânico real vira uma ligação
    automática para alguém que pode estar sob ameaça.
    """
    assert eventos.em_escopo("PANICO")
    assert eventos.elegivel_para_ia("PANICO") is True
    assert eventos.PANICO.exige_triagem_previa is True
    assert eventos.PANICO.motivo_inelegibilidade is None


def test_todo_evento_critico_exige_triagem_previa() -> None:
    """A regra vale por criticidade, não por nome.

    Um evento CRÍTICO novo entrando no catálogo sem esta trava significaria a
    IA ligando às cegas — exatamente o que a v2.0 existe para impedir.
    """
    for tipo in eventos.CATALOGO:
        if tipo.criticidade == "CRITICA" and tipo.elegivel_ia:
            assert tipo.exige_triagem_previa, f"{tipo.codigo} é crítico e liga sem triagem"


def test_triagem_previa_implica_elegibilidade() -> None:
    """Triar sem poder tratar não faz sentido — seria custo sem consequência."""
    for tipo in eventos.CATALOGO:
        if tipo.exige_triagem_previa:
            assert tipo.elegivel_ia


def test_panico_so_fecha_com_os_desfechos_previstos() -> None:
    """A lista branca do evento mais caro de errar, escrita por extenso.

    ⚠️ **O terceiro entrou em 10/09/2026 e não é desfecho do alarme.** Os dois
    primeiros dizem o que aconteceu com o veículo; `numero_removido_a_pedido`
    diz que o número não é do cliente. O alarme continua sem causa apurada e
    o veículo segue disparando para quem mais estiver no cadastro.

    Está aqui por extenso, e não por contagem, porque a lista do pânico é a que
    menos pode crescer por descuido: cada nome novo é uma porta a mais para
    fechar sozinho um caso que pode ser real.
    """
    assert set(eventos.PANICO.desfechos_permitidos) == {
        "acionamento_acidental_confirmado",
        "alarme_falso_confirmado_por_triagem",
        "numero_removido_a_pedido",
    }
    assert eventos.desfecho_permitido("PANICO", "qualquer_coisa") is False


def test_limiar_de_escalonamento_e_um_numero_da_operacao() -> None:
    """Mora no domínio, não dentro do prompt.

    Mudar o ponto em que a Bahrd troca contenção por segurança não pode exigir
    reescrever instrução de modelo — e precisa aparecer na auditoria.
    """
    assert 0 < eventos.LIMIAR_ESCALONAMENTO <= 100


def test_tipo_desconhecido_nao_e_elegivel() -> None:
    """Fecha em `False` para o que não conhece.

    Um tipo novo aparecendo no webhook do sistema da Bahrd não pode virar
    atendimento automático por omissão.
    """
    assert eventos.em_escopo("EXCESSO_VELOCIDADE") is False
    assert eventos.elegivel_para_ia("EXCESSO_VELOCIDADE") is False
    assert eventos.por_codigo("EXCESSO_VELOCIDADE") is None


@pytest.mark.parametrize("codigo", [t.codigo for t in eventos.CATALOGO if t.elegivel_ia])
def test_evento_elegivel_tem_playbook_e_canal(codigo: str) -> None:
    tipo = eventos.por_codigo(codigo)
    assert tipo is not None
    assert tipo.playbook, "evento elegível sem playbook não tem como ser conduzido"
    assert tipo.cascata_canais, "evento elegível precisa de ao menos um canal"


def test_lista_branca_vazia_significa_ia_nao_fecha() -> None:
    """Lista branca vazia não é esquecimento — é a decisão de não deixar fechar.

    Separado do teste acima de propósito: `ROUBO_ATIVO_MOVIMENTO` é elegível e
    tem lista vazia por escolha. Todos os outros elegíveis precisam ter uma,
    senão a IA fecharia com qualquer coisa.
    """
    sem_lista = {t.codigo for t in eventos.CATALOGO if t.elegivel_ia and not t.desfechos_permitidos}
    assert sem_lista == {"ROUBO_ATIVO_MOVIMENTO"}


def test_janelas_batem_com_os_playbooks() -> None:
    """90 s pela bateria reserva; 60 s pelo risco de reboque; 150 s no pânico.

    O pânico era 30 s, revisado em 25/08/2026. Aquele número foi escrito para o
    pânico que tenta **ligação** primeiro, e ali o silêncio significa alguma
    coisa: o telefone tocou e ninguém atendeu. Por WhatsApp não significa — o
    celular pode estar no bolso. A janela subiu junto com a espera para as duas
    não se contradizerem: o modelo lê este número em toda conversa.
    """
    assert eventos.REMOCAO_BATERIA.janela_s == 90
    assert eventos.MOVIMENTO_SEM_IGNICAO.janela_s == 60
    assert eventos.PANICO.janela_s == 150


def test_movimento_sem_ignicao_exige_confirmacao_dupla() -> None:
    """É o único playbook com essa exigência, e o motivo é o roubo por reboque."""
    assert eventos.MOVIMENTO_SEM_IGNICAO.requer_confirmacao_dupla
    assert not eventos.REMOCAO_BATERIA.requer_confirmacao_dupla


def test_desfecho_fora_da_lista_branca_e_recusado() -> None:
    assert eventos.desfecho_permitido("REMOCAO_BATERIA", "veiculo_em_manutencao")
    assert eventos.desfecho_permitido("REMOCAO_BATERIA", "reboque_autorizado") is False


@pytest.mark.parametrize("codigo", [t.codigo for t in eventos.CATALOGO if t.elegivel_ia])
def test_playbook_do_evento_elegivel_existe_em_disco(codigo: str) -> None:
    """O arquivo tem de existir antes da primeira ligação, não durante.

    `blocos_de_sistema` levanta `PromptAusente` quando falta o arquivo — o que
    está certo, mas descobrir isso em produção significa uma ocorrência que
    caiu no `except` genérico. Aqui o erro aparece no commit.
    """
    from central_ia.agent.prompts import RAIZ_PROMPTS

    tipo = eventos.por_codigo(codigo)
    assert tipo is not None and tipo.playbook
    caminho = RAIZ_PROMPTS / "playbooks" / f"{tipo.playbook}.md"
    assert caminho.is_file(), f"{codigo}: playbook {tipo.playbook}.md não existe"
