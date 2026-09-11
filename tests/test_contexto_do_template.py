"""A IA precisa saber o que o cliente já leu.

**Conversa real, 25/08/2026.** O template chegou dizendo evento, placa e local.
O motorista respondeu "Olá vou ver aqui". A IA respondeu:

    Bom dia, Bruno! Aqui é a assistente virtual da Bahrd. O sistema acusou
    agora que a bateria do caminhão ABC1234 foi desligada. Beleza, fico no
    aguardo.

Três frases de preâmbulo para uma de resposta, e as três repetindo o que ele
tinha acabado de ler. A causa não era o prompt: o histórico **mentia**. O envio
do template ia para `sessao.anotar()`, que é trilha de auditoria e o modelo não
lê. Do ponto de vista dele não havia assistente nenhum antes de si — e quem
nunca falou se apresenta.

Estes testes guardam as duas metades da correção: que o corpo do modelo é
recuperável com fidelidade, e que a lista de modelos do código não diverge da
lista de modelos que existem de verdade. A segunda metade importa mais do que
parece: um nome que não bate faz a IA achar que mandou uma mensagem que
ninguém recebeu, e aí ela responde a uma conversa que não aconteceu.
"""

from __future__ import annotations

import re

import pytest

from central_ia.api.rotas.eventos import (
    MODELOS_DE_ALERTA,
    TEMPLATE_ALERTA,
    TEMPLATE_ALERTA_MAPA,
    TEMPLATE_PROPRIO,
)
from central_ia.integrations.mensageria import modelos

PLACA = "ABC-1234"
LOCAL = "Rua Comendador Roseira, Curitiba - PR"
EVENTO = "Remoção de bateria"
HORARIO = "18:30"

#: Os quatro do modelo novo, na ordem que a rota manda.
ALERTA = [EVENTO, PLACA, HORARIO, LOCAL]

#: Todo nome que a rota pode escolher: os quatro do alerta e os quatro de cada
#: evento com modelo próprio — geração em uso e reserva, com e sem mapa.
USADOS_PELA_ROTA = sorted(
    set(MODELOS_DE_ALERTA) | {nome for par in TEMPLATE_PROPRIO.values() for nome in par}
)


# ─────────────────────── O texto que o cliente leu ───────────────────────


def test_corpo_sai_com_os_parametros_no_lugar() -> None:
    texto = modelos.corpo(TEMPLATE_ALERTA, ALERTA)

    assert texto is not None
    # ⚠️ Não basta o valor aparecer: ele tem que aparecer NO SLOT dele. A Meta
    # aceita numa boa trocar {{1}} com {{2}} — ela não sabe o que cada um
    # significa —, e o sintoma seria o tipo do evento no lugar da placa.
    assert f"ocorrência de *{EVENTO}*" in texto
    assert f"no veículo *{PLACA}*" in texto
    assert f"Horário: {HORARIO}" in texto
    assert f"Local: {LOCAL}" in texto
    assert "{{" not in texto, "sobrou marcador de parâmetro"
    # O corpo inteiro, não só os campos: é o que o cliente tem na tela.
    assert "Escolha uma das opções abaixo" in texto


def test_o_tipo_do_evento_e_parametro_e_nao_texto_fixo() -> None:
    """O ganho da unificação de 26/08: um modelo serve os onze do catálogo.

    Se alguém voltar a escrever o nome do evento dentro do corpo, este teste
    cai — e cai antes de a Meta receber um pedido de modelo por tipo de evento.
    """
    bateria = modelos.corpo(TEMPLATE_ALERTA, ALERTA)
    movimento = modelos.corpo(
        TEMPLATE_ALERTA, ["Movimento com ignição desligada", PLACA, "02:14", LOCAL]
    )

    assert bateria is not None and movimento is not None
    assert "Remoção de bateria" in bateria
    assert "Movimento com ignição desligada" in movimento
    assert "Remoção de bateria" not in movimento


def test_as_duas_variantes_tem_o_mesmo_corpo() -> None:
    """Mapa e texto só diferem no cabeçalho, e é isso que os torna trocáveis.

    A rota tenta o com mapa e cai no de texto quando não há coordenada. Se os
    corpos divergirem, essa queda passa a mudar o que o cliente lê — e o
    `parametros` do manifesto, que é o mesmo para os dois, mente para um deles.
    """
    com_mapa = modelos.corpo(TEMPLATE_ALERTA_MAPA, ALERTA)
    so_texto = modelos.corpo(TEMPLATE_ALERTA, ALERTA)

    assert com_mapa is not None and com_mapa == so_texto
    # E o `Local:` está nos dois: no modelo antigo o com mapa não tinha a linha.
    assert f"Local: {LOCAL}" in com_mapa


def test_modelo_desconhecido_nao_inventa() -> None:
    assert modelos.corpo("evento_que_nao_existe", [PLACA]) is None
    assert modelos.como_turno("evento_que_nao_existe", [PLACA]) is None


def test_parametro_faltando_fica_visivel() -> None:
    """Melhor mostrar `{{2}}` do que inventar um valor que o cliente não viu.

    Um valor inventado aqui vira a IA discutindo um local que nunca foi
    enviado — erro silencioso e caro de achar. O marcador cru denuncia.
    """
    texto = modelos.corpo(TEMPLATE_ALERTA, [EVENTO, PLACA])

    assert texto is not None
    assert f"no veículo *{PLACA}*" in texto
    assert "{{3}}" in texto
    assert "{{4}}" in texto


# ─────────────────────── O turno que entra no histórico ───────────────────────


def test_turno_avisa_que_a_mensagem_ja_foi_entregue() -> None:
    """Três avisos, cada um evitando um erro diferente.

    Que já foi entregue (não repita), que o cliente já leu (não explique o
    evento de novo) e que o texto não é dele (não imite o "Atenciosamente" —
    o modelo copia o estilo do que lê, e a persona é o oposto disso).
    """
    turno = modelos.como_turno(TEMPLATE_ALERTA, ALERTA)

    assert turno is not None
    assert "já entregue ao cliente" in turno
    assert "não escrito por você" in turno
    assert "Não repita" in turno
    # E o texto de verdade vem junto, senão o aviso não serve para nada.
    assert f"no veículo *{PLACA}*" in turno


def test_turno_menciona_o_mapa_quando_houve_mapa() -> None:
    com = modelos.como_turno(TEMPLATE_ALERTA_MAPA, ALERTA, com_mapa=True)
    sem = modelos.como_turno(TEMPLATE_ALERTA, ALERTA, com_mapa=False)

    assert com is not None and "cartão de localização" in com
    assert sem is not None and "cartão de localização" not in sem


# ─────────────────────── As duas plateias, na sessão real ───────────────────────


def test_registrar_template_escreve_nos_dois_lugares() -> None:
    """Modelo e operador leem listas diferentes, e cada um recebe o seu texto.

    `historico` é o que vai no prompt; `falas` é o que o painel desenha. Colar
    o mesmo texto nos dois é o erro fácil aqui — e ele aparece como instrução
    entre colchetes na telinha do operador.
    """
    from central_ia.domain import eventos as catalogo
    from central_ia.orchestration.sessao_whatsapp import SESSOES

    sessao = SESSOES.abrir(
        "+5541999999999",
        catalogo.por_codigo("REMOCAO_BATERIA"),
        "TEXTO",
        {"placa": PLACA, "interlocutor": "Bruno"},
    )
    antes = len(sessao.historico)

    sessao.registrar_template(
        modelos.como_turno(TEMPLATE_ALERTA, ALERTA) or "",
        modelos.corpo(TEMPLATE_ALERTA, ALERTA) or "",
        modelos.botoes(TEMPLATE_ALERTA),
    )

    assert len(sessao.historico) == antes + 1
    do_modelo = sessao.historico[-1]
    assert do_modelo.papel == "assistant"
    assert "já entregue ao cliente" in do_modelo.conteudo

    assert len(sessao.falas) == 1
    do_painel = sessao.falas[-1]
    assert do_painel.quem == "ia"
    assert do_painel.tipo == "template"
    # Os botões que o cliente teve para tocar. Desde 26/08 eles ABREM conversa
    # em vez de levar para a loja — um "não respondeu" mudou de sentido.
    assert do_painel.botoes == ["Preciso de ajuda!", "Está tudo bem!"]
    assert f"no veículo *{PLACA}*" in do_painel.texto
    assert "já entregue ao cliente" not in do_painel.texto, "andaime vazou para o operador"


def test_template_nao_gasta_turno_nem_custo() -> None:
    """O texto foi aprovado pela Meta; o modelo não participou.

    Gastar um dos `MAX_TURNOS_IA` aqui tiraria da conversa de verdade um turno
    que ela vai precisar — e o custo do disparo é contabilizado noutro lugar.
    """
    from central_ia.domain import eventos as catalogo
    from central_ia.orchestration.sessao_whatsapp import SESSOES

    sessao = SESSOES.abrir(
        "+5541988888888", catalogo.por_codigo("REMOCAO_BATERIA"), "TEXTO", {"placa": PLACA}
    )

    sessao.registrar_template("para o modelo", "para o operador", [])

    assert sessao.turnos_ia == 0
    assert sessao.custo_usd == 0.0


# ─────────────────────── Contra a divergência ───────────────────────


@pytest.mark.parametrize("nome", USADOS_PELA_ROTA)
def test_todo_modelo_usado_pela_rota_tem_corpo_recuperavel(nome: str) -> None:
    """O guarda mais importante do arquivo.

    A rota escolhe o modelo pelo nome; o manifesto encontra o arquivo por esse
    mesmo nome. Se alguém renomear um e esquecer o outro, o envio continua
    funcionando — a Meta conhece o nome — e o que quebra é só o histórico, em
    silêncio. A IA volta a se apresentar e a recontar o evento, e ninguém liga
    isso a um rename feito semanas antes.
    """
    assert modelos.corpo(nome, ["X", "Y"]) is not None, f"modelo '{nome}' fora do manifesto"


@pytest.mark.parametrize("entrada", modelos._manifesto().values(), ids=lambda e: e["nome"])
def test_manifesto_declara_a_quantidade_certa_de_parametros(entrada: dict) -> None:
    """`{{1}}`, `{{2}}` no corpo têm de bater com o que o manifesto promete.

    Errar para menos deixa marcador cru na tela do cliente; errar para mais faz
    a Meta recusar o envio inteiro — e aí não sai notificação nenhuma.
    """
    corpo = modelos._corpo_cru(entrada["nome"])
    assert corpo is not None

    marcadores = {int(n) for n in re.findall(r"\{\{(\d+)\}\}", corpo)}
    declarados = len(entrada["parametros"])

    assert marcadores == set(range(1, declarados + 1)), (
        f"{entrada['nome']}: corpo usa {sorted(marcadores)}, "
        f"manifesto declara {declarados} parâmetro(s)"
    )
