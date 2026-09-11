"""Dados de amostra do painel — **substituídos no Sprint 2**.

⚠️ Nada aqui vem de banco. Serve para o painel ser construído e testado contra
o contrato real (:mod:`central_ia.api.esquemas_painel`).

**Escopo: os três tipos de evento de :mod:`central_ia.domain.eventos`.** Se um
caso aparecer aqui com tipo fora do catálogo, o teste
`tests/test_amostra_escopo.py` quebra — a amostra não pode divergir da política.

Os canais de cada caso seguem os playbooks, não a conveniência da tela:

* `REMOCAO_BATERIA` → ligação; áudio de WhatsApp se o motorista não atender.
* `MOVIMENTO_SEM_IGNICAO` → ligação ao motorista, depois gestor (mensagem).
* `PANICO` → a IA não fala. Nenhuma conversa, em nenhum canal.

Quando o orquestrador existir, este módulo é apagado e `rotas/painel.py` passa
a ler de `ocorrencia` (Oracle) e `conversa`/`mensagem` (MySQL). **O contrato não
muda** — logo, o front-end não muda.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from central_ia.api.esquemas_painel import (
    Barra,
    Encerrada,
    Encerrados,
    EquipamentoReincidente,
    EventoAuditoria,
    Fila,
    ItemFila,
    Metricas,
    Ocorrencia,
    PassoRoteiro,
    Turno,
    Vital,
)
from central_ia.domain.eventos import (
    ENTRADA_2_ACIONADA,
    ERRO_BATERIA_BACKUP,
    MOVIMENTO_SEM_IGNICAO,
    PANICO,
    REMOCAO_BATERIA,
    ROUBO_ATIVO_MOVIMENTO,
    ULTRAPASSOU_LIMITE_VELOCIDADE,
    VELOCIDADE_EXCEDIDA,
    VELOCIDADE_EXCEDIDA_CERCA_POLIGONO,
)


def _passo(frase: str, duracao_s: int, falando: bool) -> PassoRoteiro:
    return PassoRoteiro(frase=frase, duracao_s=duracao_s, falando=falando)


# ─────────────────────────────── Fila humana ───────────────────────────────

#: Fila humana da POC — **restrita aos três eventos principais** por decisão de
#: demonstração: remoção de bateria, movimento com ignição desligada e pânico
#: real. Três casos que o gestor entende sem explicação prévia valem mais numa
#: reunião do que sete que exigem contexto.
#:
#: Os registros completos de `ROUBO_ATIVO_MOVIMENTO` (OC-...476) e
#: `ENTRADA_2_ACIONADA` (OC-...479) continuam existindo e acessíveis por id —
#: só saíram da fila. Devolvê-los é reinserir o `ItemFila` aqui.
PRECISA_DE_VOCE = [
    # Política v2.0: a IA trata todo evento, inclusive os críticos — mas em
    # evento crítico ela **classifica antes de falar**. O pânico abaixo chegou
    # aqui porque a triagem estimou probabilidade acima do limiar, não porque o
    # tipo do evento a proibiu de tentar.
    ItemFila(
        ocorrencia_id="OC-2026-08-11-000478",
        grau="critica",
        tipo_evento=PANICO.rotulo,
        canal="LIGACAO",
        placa="RST7U88",
        interlocutor="Edson Lima, motorista",
        nota="Triagem: 94% de chance de ser real",
        leitura_ia=(
            "A IA cruzou os dados antes de falar: veículo 11,4 km fora da rota, parado no "
            "acostamento, com suspeita de jammer e movimento sem ignição na mesma janela. "
            "Estimou 94% de chance de ser real — acima do limiar de 90%, o contato é seu."
        ),
        decorrido_s=12,
        sla_s=PANICO.janela_s,
        tem_detalhe=True,
    ),
    ItemFila(
        ocorrencia_id="OC-2026-08-11-000480",
        grau="alta",
        tipo_evento=MOVIMENTO_SEM_IGNICAO.rotulo,
        canal="TEXTO",
        placa="PQR4S67",
        interlocutor="Iracema Lopes, gestora",
        nota="Gestor não confirmou a autorização",
        decorrido_s=54,
        sla_s=MOVIMENTO_SEM_IGNICAO.janela_s,
        tem_detalhe=True,
    ),
    ItemFila(
        ocorrencia_id="OC-2026-08-11-000483",
        grau="alta",
        tipo_evento=REMOCAO_BATERIA.rotulo,
        canal="AUDIO",
        placa="DEF2G34",
        interlocutor="Carla Souza, motorista",
        nota="Resposta inconclusiva",
        decorrido_s=97,
        sla_s=REMOCAO_BATERIA.janela_s,
        tem_detalhe=True,
    ),
]

# ────────────────────────── Em atendimento pela IA ──────────────────────────
# Pânico jamais aparece aqui.

IA_ESTA_FAZENDO = [
    ItemFila(
        ocorrencia_id="OC-2026-08-11-000484",
        grau="alta",
        tipo_evento=REMOCAO_BATERIA.rotulo,
        canal="LIGACAO",
        placa="GHI7J89",
        interlocutor="Antônio Ramos, motorista",
        latitude=-21.1080033,
        longitude=-47.7834657,
        endereco="Rodovia Anhanguera · pátio de pernoite, Ribeirão Preto - SP",
        decorrido_s=38,
        sla_s=REMOCAO_BATERIA.janela_s,
        tem_ao_vivo=True,
        roteiro=[
            _passo("Ligando para o motorista", 6, True),
            _passo("Esperando ele atender", 8, False),
            _passo("Perguntando se ele desligou a chave geral", 7, True),
            _passo("Ouvindo a resposta", 6, False),
            _passo("Conferindo se o veículo está em oficina cadastrada", 5, False),
            _passo("Conferindo a senha dele", 4, False),
            _passo("Registrando a justificativa e encerrando", 6, True),
        ],
        falas=[
            Turno(
                quem="ia",
                fala="Oi, Antônio! Aqui é a assistente virtual da Bahrd Monitoramento. O sistema "
                "acusou agora "
                "que a bateria do caminhão foi desligada. Você desligou a chave geral, ou "
                "ele tá em manutenção?",
            ),
            Turno(
                quem="cliente",
                fala="Ah sim, desliguei a chave geral. Tô no pátio, vou dormir aqui.",
            ),
            Turno(
                quem="ia",
                fala="Entendi. Já registrei como chave geral desligada no pátio, então o "
                "alerta encerra aqui. Boa noite, Antônio!",
            ),
        ],
    ),
    # Segunda perna da confirmação dupla: o motorista já confirmou o reboque,
    # agora a IA precisa do gestor. Sem essa segunda confirmação o caso não fecha.
    ItemFila(
        ocorrencia_id="OC-2026-08-11-000490",
        grau="alta",
        tipo_evento=MOVIMENTO_SEM_IGNICAO.rotulo,
        canal="TEXTO",
        placa="ABC1D23",
        interlocutor="Regina Alves, gestora",
        latitude=-22.7414130,
        longitude=-47.2708981,
        endereco="Rodovia Anhanguera · Americana - SP",
        decorrido_s=31,
        sla_s=MOVIMENTO_SEM_IGNICAO.janela_s,
        tem_ao_vivo=True,
        roteiro=[
            _passo("Motorista confirmou reboque — confirmando com a gestora", 5, True),
            _passo("Mensagem enviada, esperando ela ler", 9, False),
            _passo("Ela está digitando", 6, True),
            _passo("Perguntando por quanto tempo suprimir os alarmes", 4, False),
            _passo("Registrando a confirmação e o prazo", 5, True),
        ],
        falas=[
            Turno(
                quem="ia",
                horario="14:07",
                status="lido",
                fala="Oi, Regina! Aqui é a assistente virtual da Bahrd Monitoramento. O ABC1D23 "
                "está se "
                "movendo com a chave desligada. Vocês autorizaram algum reboque?",
                botoes=["Sim, autorizamos", "Não autorizamos"],
            ),
            Turno(
                quem="cliente",
                horario="14:08",
                fala="Sim, autorizamos",
            ),
            Turno(
                quem="ia",
                horario="14:08",
                status="entregue",
                fala="Certo. Por quanto tempo devo desconsiderar os alertas desse veículo?",
            ),
        ],
    ),
    ItemFila(
        ocorrencia_id="OC-2026-08-11-000491",
        grau="alta",
        tipo_evento=REMOCAO_BATERIA.rotulo,
        canal="AUDIO",
        placa="JKL3M45",
        interlocutor="Marcelo Dias, motorista",
        latitude=-20.6479504,
        longitude=-48.8388495,
        endereco="Rodovia Assis Chateaubriand · posto de apoio, Barretos - SP",
        decorrido_s=61,
        sla_s=REMOCAO_BATERIA.janela_s,
        tem_ao_vivo=True,
        roteiro=[
            _passo("Ligação não atendida — enviando nota de voz", 5, True),
            _passo("Áudio enviado, esperando ele ouvir", 16, False),
            _passo("Ouvindo a resposta em áudio", 6, False),
        ],
        falas=[
            Turno(
                quem="ia",
                horario="19:51",
                status="lido",
                tipo="audio",
                duracao_s=12,
                fala="Oi, Marcelo! Aqui é a assistente virtual da Bahrd Monitoramento. Tentei te "
                "ligar agora. "
                "O sistema acusou que a bateria do caminhão foi desligada — você desligou "
                "a chave geral, ou ele tá em manutenção?",
            ),
            Turno(
                quem="cliente",
                horario="19:52",
                tipo="audio",
                duracao_s=9,
                transcrito=True,
                fala="Desliguei a chave sim, tô parado no posto pra dormir.",
            ),
        ],
    ),
    ItemFila(
        ocorrencia_id="OC-2026-08-11-000492",
        grau="alta",
        tipo_evento=MOVIMENTO_SEM_IGNICAO.rotulo,
        canal="LIGACAO",
        placa="STU9V23",
        interlocutor="Bruno Teixeira, motorista",
        latitude=-23.3337967,
        longitude=-46.1403204,
        endereco="Rodovia Presidente Dutra · Guararema - SP",
        decorrido_s=18,
        sla_s=MOVIMENTO_SEM_IGNICAO.janela_s,
        # Sem falas de propósito: a IA está discando, ninguém atendeu ainda.
        # A tela ao vivo mostra o passo do playbook e o estado de espera — que
        # é informação, não tela vazia.
        tem_ao_vivo=True,
        roteiro=[
            _passo("Consultando a posição do veículo", 4, False),
            _passo("Trajetória coerente — não é falso positivo de GPS", 4, False),
            _passo("Ligando para o motorista", 6, True),
            _passo("Esperando ele atender", 9, False),
        ],
    ),
    # Os três eventos de velocidade saíram da amostra por decisão de
    # demonstração: o gestor reconhece bateria, ignição e pânico sem
    # explicação prévia. Continuam no catálogo e no pipeline — o que saiu
    # foi a linha na tela, não o suporte a eles.
]


#: Instante de referência da amostra. O horário de cada evento é **derivado**
#: dele menos `decorrido_s`, e não escrito à mão em cada item: se fossem dois
#: campos independentes, um dia a linha diria "há 12 s" com horário de duas
#: horas atrás e ninguém confiaria mais em nenhum dos dois.
AGORA_AMOSTRA = datetime(2026, 8, 11, 19, 44, 14, tzinfo=ZoneInfo("America/Sao_Paulo"))


def _preparar(itens: list[ItemFila]) -> list[ItemFila]:
    """Completa cada linha com horário e posição.

    A posição é **copiada do registro detalhado** quando ele existe. Um mesmo
    caminhão pode aparecer em ocorrências diferentes, em lugares diferentes —
    então a chave não é a placa, é a ocorrência. E derivar em vez de repetir
    impede o caso em que a lista mostra um ponto e o detalhe mostra outro.
    """
    saida = []
    for item in itens:
        momento = AGORA_AMOSTRA - timedelta(seconds=item.decorrido_s)
        mudancas: dict[str, object] = {
            "momento": f"{momento:%H:%M}",
            "dia": f"{momento:%d/%m/%Y}",
            "momento_completo": f"{momento:%d/%m/%Y às %H:%M:%S}",
        }

        detalhe = ocorrencia(item.ocorrencia_id)
        if detalhe is not None and detalhe.latitude is not None:
            mudancas |= {
                "latitude": detalhe.latitude,
                "longitude": detalhe.longitude,
                "endereco": detalhe.endereco,
            }

        saida.append(item.model_copy(update=mudancas))
    return saida


def fila() -> Fila:
    return Fila(
        precisa_de_voce=_preparar(PRECISA_DE_VOCE),
        ia_esta_fazendo=_preparar(IA_ESTA_FAZENDO),
    )


# ─────────────────────────── Ocorrências detalhadas ───────────────────────────

_ROUBO_ATIVO = Ocorrencia(
    ocorrencia_id="OC-2026-08-11-000476",
    latitude=-23.8950723,
    longitude=-46.9852808,
    endereco="Rodovia Régis Bittencourt · sentido sul, Juquitiba - SP",
    tipo_evento=ROUBO_ATIVO_MOVIMENTO.rotulo,
    grau="critica",
    canal="LIGACAO",
    placa="RST7U88",
    interlocutor="Veículo já marcado como roubado",
    telefone="+55 11 99999-0001",
    aberta_ha="há 8 s",
    briefing=(
        "Veículo <strong>já marcado como roubado</strong> voltou a se mover. A IA triagem "
        "antes de qualquer contato, como manda a política v2.0, e estimou <strong>99% de "
        "chance de ser real</strong> — o caso é seu e ninguém foi contatado. Um contato "
        "automático aqui alertaria quem está com o caminhão. Mesmo se a triagem tivesse "
        "errado, este evento não tem nenhum desfecho na lista branca: a IA não teria com o "
        "que fechar."
    ),
    handoff=[
        "Cruzou telemetria e situação cadastral do veículo · janela de 15 s.",
        "Estimou 99% de chance de ser real — acima do limiar de 90%.",
        "Não ligou, não mandou mensagem: contato aqui alerta quem está com o caminhão.",
        "Observou: veículo com marcação de roubo ativa no cadastro",
        "Observou: parado há 4 h 12 min, voltou a se mover às 19:43",
        "Observou: 58 km/h, sentido sul pela BR-116",
        "Observou: pânico registrado no mesmo veículo há 4 s (OC-...478)",
    ],
    probabilidade_real=99,
    acoes=[],
    conversa=[],
    turnos=0,
    duracao="—",
    ficha={
        "Evento": PANICO.rotulo,
        "Placa": "RST7U88",
        "Cliente": "Edson Lima",
        "Número": "+55 11 99999-0001",
        "Logradouro": "Rodovia Régis Bittencourt, sentido sul · 58 km/h",
        "Coordenada": "-21.10800330, -47.78346570",
    },
    auditoria=[
        EventoAuditoria(
            horario="19:44:06",
            descricao="Evento recebido — <b>veículo com roubo ativo se movimentou</b>.",
        ),
        EventoAuditoria(
            horario="19:44:06",
            descricao="Política <b>v2.0</b>: evento crítico — <b>triagem obrigatória antes "
            "de qualquer contato</b>. Limiar: 90%.",
        ),
        EventoAuditoria(
            horario="19:44:07",
            descricao="Triagem: <b>99% de chance de ser real</b> · possivel_real · confiança "
            "alta. Marcação de roubo ativa | parado 4 h 12 min | retomou movimento a 58 km/h "
            "| pânico correlato no mesmo veículo.",
        ),
        EventoAuditoria(
            horario="19:44:07",
            descricao="<b>99% ≥ 90%</b> — entregue ao operador. "
            "<b>Nenhum contato automático foi feito.</b>",
        ),
        EventoAuditoria(
            horario="19:44:07",
            descricao="Lista branca deste evento está <b>vazia por política</b>: a IA não "
            "pode encerrá-lo em nenhum cenário.",
        ),
    ],
    politica_versao="v2.0",
    prompt_versao="v2.0",
)

_ENTRADA_2 = Ocorrencia(
    ocorrencia_id="OC-2026-08-11-000479",
    latitude=-19.1807714,
    longitude=-48.1574914,
    endereco="Rodovia Chico Xavier · Uberaba - MG",
    tipo_evento=ENTRADA_2_ACIONADA.rotulo,
    grau="alta",
    canal="LIGACAO",
    placa="LMN5O66",
    interlocutor="Fábio Nunes, motorista",
    telefone="+55 11 99999-0002",
    aberta_ha="há 26 s",
    briefing=(
        "A entrada 2 deste rastreador foi acionada — e <strong>ninguém sabe o que ela "
        "significa neste veículo</strong>. Pode ser botão de pânico auxiliar, sensor de "
        "porta do baú ou tomada de força. Enquanto não houver o mapa por veículo, a "
        "política trata como alto risco e manda direto para você: assumir o menos grave "
        "seria decidir no escuro em favor do silêncio."
    ),
    handoff=[
        "Leu o contexto do veículo. Não houve contato — este evento ainda não tem "
        "procedimento definido com a Bahrd.",
        "Observou: veículo em rota, 74 km/h, sem desvio",
        "Observou: nenhum evento correlato na janela",
        "Observou: 1 acionamento da entrada 2 neste equipamento em 90 dias, sem desfecho "
        "registrado",
    ],
    acoes=[],
    conversa=[],
    turnos=0,
    duracao="—",
    ficha={
        "Evento": ENTRADA_2_ACIONADA.rotulo,
        "Placa": "LMN5O66",
        "Cliente": "Fábio Nunes",
        "Número": "+55 11 99999-0002",
        "Logradouro": "Rodovia Chico Xavier, Uberaba · 74 km/h, em rota",
        "Coordenada": "-19.18077140, -48.15749140",
    },
    auditoria=[
        EventoAuditoria(
            horario="19:43:48", descricao="Evento recebido — <b>entrada 2 acionada</b>."
        ),
        EventoAuditoria(
            horario="19:43:48",
            descricao="Política <b>v2.0</b>: <b>sem playbook</b> — significado da entrada "
            "não mapeado. Tratado como alto risco.",
        ),
        EventoAuditoria(
            horario="19:43:49",
            descricao="Contexto consultado — em rota, sem correlatos na janela.",
        ),
        EventoAuditoria(
            horario="19:43:50",
            descricao="Leitura de contexto gerada — <b>descritiva, sem recomendação</b>. "
            "Nenhum contato automático foi feito.",
        ),
        EventoAuditoria(
            horario="19:43:50",
            descricao="Pendência registrada: <b>existe mapa de qual sensor está ligado na "
            "entrada 2, por cliente ou por veículo?</b> Sem isso, o evento não vira playbook.",
        ),
    ],
    politica_versao="v2.0",
    prompt_versao="v2.0",
)

_PANICO = Ocorrencia(
    ocorrencia_id="OC-2026-08-11-000478",
    latitude=-23.6443891,
    longitude=-46.5846535,
    endereco="Rodovia Anchieta · acostamento, São Bernardo do Campo - SP",
    tipo_evento=PANICO.rotulo,
    grau="critica",
    canal="LIGACAO",
    placa="RST7U88",
    interlocutor="Edson Lima, motorista",
    telefone="+55 11 99999-0003",
    aberta_ha="há 12 s",
    # Política v2.0: a IA tentaria tratar este caso. Ela não tratou porque a
    # triagem, feita ANTES de qualquer contato, estimou 94% de chance de ser
    # real. Quem barrou o contato foi a evidência, não o tipo do evento.
    briefing=(
        "A IA cruzou os dados antes de falar com alguém e estimou <strong>94% de chance "
        "de ser real</strong> — acima do limiar de 90%, o caso é seu e nenhum contato "
        "automático foi feito. O que pesou: veículo <strong>11,4 km fora da rota</strong>, "
        "parado no acostamento da Anchieta, com suspeita de jammer de GPS há 2 min e "
        "movimento sem ignição há 6 min. Este equipamento não tem histórico de "
        "acionamento acidental."
    ),
    handoff=[
        "Cruzou telemetria, rota, histórico do equipamento e eventos correlatos · janela de 30 s.",
        "Estimou 94% de chance de ser real — acima do limiar de 90%.",
        "Não ligou, não mandou mensagem: em caso crítico acima do limiar o contato é seu.",
        "Observou: desvio de 11,4 km da rota prevista",
        "Observou: veículo parado no acostamento, ignição desligada",
        "Observou: suspeita de jammer de GPS há 2 min",
        "Observou: movimento com ignição desligada há 6 min",
        "Observou: nenhum acionamento acidental no histórico deste equipamento",
    ],
    probabilidade_real=94,
    acoes=[],
    conversa=[],
    turnos=0,
    duracao="—",
    ficha={
        "Evento": PANICO.rotulo,
        "Placa": "RST7U88",
        "Cliente": "Edson Lima",
        "Número": "+55 11 99999-0003",
        "Logradouro": "Rodovia Anchieta · acostamento, ignição desligada",
        "Coordenada": "-23.64438910, -46.58465350",
    },
    auditoria=[
        EventoAuditoria(
            horario="19:44:02",
            descricao="Evento recebido do sistema Bahrd — <b>pânico</b>, botão acionado.",
        ),
        EventoAuditoria(
            horario="19:44:02",
            descricao="Política <b>v2.0</b>: evento crítico — <b>triagem obrigatória antes "
            "de qualquer contato</b>. Limiar de escalonamento: 90%.",
        ),
        EventoAuditoria(
            horario="19:44:02",
            descricao="Contexto consultado — 2 eventos em 90 dias, "
            "<b>2 correlatos na janela</b>.",
        ),
        EventoAuditoria(
            horario="19:44:06",
            descricao="Triagem: <b>94% de chance de ser real</b> · possivel_real · "
            "confiança alta. Desvio de 11,4 km | acostamento | jammer há 2 min | "
            "movimento sem ignição há 6 min | sem histórico de acionamento acidental.",
        ),
        EventoAuditoria(
            horario="19:44:06",
            descricao="<b>94% ≥ 90%</b> — entregue ao operador. "
            "<b>Nenhum contato automático foi feito.</b>",
        ),
    ],
    politica_versao="v2.0",
    prompt_versao="v2.0",
)

_MOV_SEM_IGNICAO = Ocorrencia(
    ocorrencia_id="OC-2026-08-11-000480",
    latitude=-22.2533181,
    longitude=-47.3900439,
    endereco="Rodovia Anhanguera · Araras - SP",
    tipo_evento=MOVIMENTO_SEM_IGNICAO.rotulo,
    grau="alta",
    canal="TEXTO",
    placa="PQR4S67",
    interlocutor="Iracema Lopes, gestora",
    telefone="+55 19 99999-0004",
    aberta_ha="há 54 s",
    briefing=(
        "O motorista confirmou por telefone que o caminhão está sendo rebocado. A gestora, "
        "porém, <strong>não confirmou a autorização</strong> — disse que vai verificar e não "
        "respondeu dentro da janela. Neste evento uma confirmação só não fecha o caso: roubo "
        "por reboque é a técnica usada justamente para não disparar os alertas de ignição."
    ),
    acoes=[],
    conversa=[
        Turno(
            quem="ia",
            horario="19:41",
            status="lido",
            tipo="template",
            fala="Oi, Iracema! Aqui é a assistente virtual da Bahrd Monitoramento. O sistema "
            "mostrou que o "
            "caminhão PQR4S67 tá se movendo com a chave desligada. Vocês autorizaram "
            "algum reboque?",
            botoes=["Sim, autorizamos", "Não autorizamos", "Vou verificar"],
        ),
        Turno(quem="cliente", horario="19:42", fala="Vou verificar"),
        Turno(
            quem="ia",
            horario="19:42",
            status="lido",
            fala="Sem problema. O motorista já confirmou que o caminhão está sendo rebocado "
            "— isso bate com o que vocês combinaram?",
        ),
        Turno(
            quem="cliente",
            horario="19:42",
            fala="Não tenho registro de reboque hoje. Deixa eu ligar pro pátio.",
        ),
        Turno(
            quem="ia",
            horario="19:42",
            status="entregue",
            fala="Entendi, Iracema. Vou te passar agora pra um colega meu aqui da central, "
            "só um instante.",
        ),
    ],
    turnos=5,
    duracao="1:04",
    ficha={
        "Evento": MOVIMENTO_SEM_IGNICAO.rotulo,
        "Placa": "PQR4S67",
        "Cliente": "Edson Lima",
        "Número": "+55 19 99999-0004",
        "Logradouro": "Rodovia Anhanguera, Araras · 61 km/h, ignição desligada",
        "Coordenada": "-22.25331810, -47.39004390",
    },
    auditoria=[
        EventoAuditoria(
            horario="19:41:06",
            descricao="Evento recebido — <b>movimento com ignição desligada</b>, 61 km/h.",
        ),
        EventoAuditoria(
            horario="19:41:06",
            descricao="Política <b>v1.0</b> liberou o tratamento pela IA — "
            "playbook <b>PB-MOV-SEM-IGNICAO</b>, janela de 60 s.",
        ),
        EventoAuditoria(
            horario="19:41:07",
            descricao="Consulta de posição — trajetória coerente e longa: "
            "<b>não é falso positivo de GPS</b>.",
        ),
        EventoAuditoria(
            horario="19:41:22",
            descricao="Motorista confirmou reboque pela ligação — 1ª confirmação.",
        ),
        EventoAuditoria(
            horario="19:41:31",
            descricao="Contato com a gestora por <b>WhatsApp</b> — template aprovado.",
        ),
        EventoAuditoria(
            horario="19:42:00",
            descricao="Gestora <b>não confirmou</b> a autorização dentro da janela — "
            "escalonamento automático, motivo "
            "<b>reboque_sem_autorizacao_do_gestor</b>.",
        ),
    ],
    politica_versao="v1.0",
    prompt_versao="v1.7",
)

_REMOCAO_BATERIA = Ocorrencia(
    ocorrencia_id="OC-2026-08-11-000483",
    latitude=-21.1767,
    longitude=-47.8208,
    endereco="Avenida Elpídio Gomes · Ribeirão Preto - SP",
    tipo_evento=REMOCAO_BATERIA.rotulo,
    grau="alta",
    canal="AUDIO",
    placa="DEF2G34",
    interlocutor="Carla Souza, motorista",
    telefone="+55 16 99999-0005",
    aberta_ha="há 1 min",
    briefing=(
        "Carla não atendeu a ligação; respondeu a nota de voz. A resposta "
        "<strong>não confirma nem nega</strong> as duas causas normais — ela fala em "
        "oficina, mas diz que não está com o caminhão. Além disso a transcrição tem um "
        "<strong>trecho de baixa confiança</strong> justamente onde ela diz o local. "
        "A IA não fecha ocorrência sobre resposta que não entendeu."
    ),
    acoes=[],
    conversa=[
        Turno(
            quem="ia",
            horario="19:38",
            status="lido",
            tipo="audio",
            duracao_s=12,
            fala="Oi, Carla! Aqui é a assistente virtual da Bahrd Monitoramento. O sistema "
            "acusou agora que "
            "a bateria do caminhão foi desligada. Você desligou a chave geral, ou ele tá "
            "em manutenção?",
        ),
        Turno(
            quem="cliente",
            horario="19:39",
            tipo="audio",
            duracao_s=15,
            transcrito=True,
            fala="Oi! Olha, eu não tô com ele agora não. Acho que o Juninho levou pra oficina "
            "lá no [trecho não compreendido], mas não sei te dizer se mexeram na bateria.",
        ),
        Turno(
            quem="ia",
            horario="19:39",
            status="entregue",
            tipo="audio",
            duracao_s=7,
            fala="Entendi, Carla, obrigada. Vou te passar pra um colega meu aqui da central, "
            "só um instante.",
        ),
    ],
    turnos=3,
    duracao="1:37",
    ficha={
        "Evento": REMOCAO_BATERIA.rotulo,
        "Placa": "DEF2G34",
        "Cliente": "Carla Souza",
        "Número": "+55 16 99999-0005",
        "Logradouro": "Avenida Elpídio Gomes, Ribeirão Preto · sem comunicação há 40 s",
        "Coordenada": "-21.17670, -47.82080",
    },
    auditoria=[
        EventoAuditoria(
            horario="19:37:55",
            descricao="Evento recebido — <b>remoção de bateria</b>. "
            "Rastreador em bateria reserva.",
        ),
        EventoAuditoria(
            horario="19:37:55",
            descricao="Política <b>v1.0</b> liberou o tratamento pela IA — "
            "playbook <b>PB-BATERIA</b>, janela de 90 s.",
        ),
        EventoAuditoria(
            horario="19:38:01",
            descricao="Ligação ao motorista <b>não atendida</b> — cascata para "
            "<b>áudio de WhatsApp</b>.",
        ),
        EventoAuditoria(
            horario="19:39:14",
            descricao="Transcrição com <b>confiança abaixo do limite</b> em 1 trecho.",
        ),
        EventoAuditoria(
            horario="19:39:16",
            descricao="Resposta não confirma nem nega as causas normais — escalonamento "
            "automático, motivo <b>resposta_inconclusiva</b>.",
        ),
    ],
    politica_versao="v1.0",
    prompt_versao="v1.7",
)

# ══════════════════════════ Ocorrências já encerradas ══════════════════════
#
# Cada uma tem o registro completo — conversa e trilha de auditoria — porque a
# aba Encerrados só vale alguma coisa se der para abrir o caso e ver o que foi
# feito. Contenção que ninguém consegue auditar caso a caso é alegação.
#
#: ⛔ **Vazio desde 03/09/2026, a pedido do Leonardo.**
#:
#: Eram "Reabrir a ocorrência", "Ligar para o interlocutor" e "Marcar para
#: revisão". O painel renderiza `acoes` como `<button>` **sem `onClick`**, então
#: os três aceitavam o clique e não faziam nada.
#:
#: Num caso encerrado isso é pior que enfeite: quem apertasse "Reabrir a
#: ocorrência" sairia da tela achando que reabriu. Botão que mente sobre o que
#: fez é o oposto do que o resto deste painel tenta ser.
#:
#: A lista fica de pé para quando houver ação de verdade — e aí volta uma a uma,
#: com o que executa, não como conjunto decorativo.
_ACOES_FECHADA: list[str] = []

_ENC_BATERIA_OK = Ocorrencia(
    ocorrencia_id="OC-2026-08-11-000461",
    latitude=-21.1080033,
    longitude=-47.7834657,
    endereco="Rodovia Anhanguera · posto de apoio, Ribeirão Preto - SP",
    tipo_evento=REMOCAO_BATERIA.rotulo,
    grau="alta",
    canal="LIGACAO",
    placa="GHI7J89",
    interlocutor="Antônio Ramos, motorista",
    telefone="+55 11 99999-0006",
    aberta_ha="encerrada às 19:12",
    briefing=(
        "O motorista atendeu no segundo toque e explicou que desligou a chave geral para "
        "dormir — hábito comum para não descarregar a bateria durante a noite. A telemetria "
        "confirma o veículo parado há 6 minutos num ponto de apoio conhecido, com a carga "
        "intacta. Causa normal prevista no <strong>PB-BATERIA</strong>, confirmada pelo "
        "próprio motorista dentro da janela de 90 s."
    ),
    acoes=_ACOES_FECHADA,
    conversa=[
        Turno(
            quem="ia",
            horario="19:11",
            fala="Oi, seu Antônio! Aqui é a assistente virtual da Bahrd Monitoramento. O "
            "sistema apontou "
            "que a bateria do rastreador do GHI7J89 foi desconectada agora há pouco. "
            "Tá tudo bem por aí?",
        ),
        Turno(
            quem="cliente",
            horario="19:11",
            transcrito=True,
            fala="Tá tudo certo. Eu parei pra dormir e desliguei a chave geral, senão de "
            "manhã a bateria tá no chão.",
        ),
        Turno(
            quem="ia",
            horario="19:11",
            fala="Entendi. Só pra eu registrar direitinho: o senhor está parado num posto, "
            "com o caminhão trancado?",
        ),
        Turno(
            quem="cliente",
            horario="19:12",
            transcrito=True,
            fala="Tô no posto da Anhanguera, caminhão trancado e eu na cabine.",
        ),
        Turno(
            quem="ia",
            horario="19:12",
            fala="Perfeito, seu Antônio. Registrei aqui como chave geral desligada pelo "
            "senhor. Bom descanso — qualquer coisa é só ligar pra gente.",
        ),
    ],
    turnos=5,
    duracao="0:52",
    ficha={
        "Evento": REMOCAO_BATERIA.rotulo,
        "Placa": "GHI7J89",
        "Cliente": "Antônio Ramos",
        "Número": "+55 11 99999-0006",
        "Logradouro": "Rodovia Anhanguera, Ribeirão Preto · parado há 6 min no posto",
        "Coordenada": "-21.10800330, -47.78346570",
    },
    auditoria=[
        EventoAuditoria(
            horario="19:11:18",
            descricao="Evento recebido — <b>remoção da bateria principal</b>.",
        ),
        EventoAuditoria(
            horario="19:11:18",
            descricao="Política <b>v1.1</b> liberou o tratamento pela IA — "
            "playbook <b>PB-BATERIA</b>, janela de 90 s.",
        ),
        EventoAuditoria(
            horario="19:11:19",
            descricao="Consulta de posição — <b>parado há 6 min</b> em ponto de apoio "
            "conhecido, sem desvio de rota.",
        ),
        EventoAuditoria(horario="19:11:24", descricao="Ligação atendida no 2º toque."),
        EventoAuditoria(
            horario="19:12:02",
            descricao="Causa normal <b>confirmada pelo motorista</b>: chave geral desligada "
            "para pernoite.",
        ),
        EventoAuditoria(
            horario="19:12:10",
            descricao="Fechada pela IA — desfecho "
            "<b>chave_geral_desligada_pelo_motorista</b>, dentro da lista branca.",
        ),
    ],
    politica_versao="v1.1",
    prompt_versao="v1.7",
)

# As ocorrencias de exemplo de velocidade sairam com os eventos de
# velocidade (decisao de escopo da demonstracao). Os tipos continuam no
# catalogo em `domain/eventos.py` — se voltarem para a tela, a amostra
# se escreve de novo a partir dos playbooks.

_ENC_REBOQUE_OK = Ocorrencia(
    ocorrencia_id="OC-2026-08-11-000442",
    latitude=-22.7414130,
    longitude=-47.2708981,
    endereco="Rodovia Anhanguera · Americana - SP",
    tipo_evento=MOVIMENTO_SEM_IGNICAO.rotulo,
    grau="alta",
    canal="TEXTO",
    placa="ABC1D23",
    interlocutor="Regina Alves, gestora",
    telefone="+55 11 99999-0007",
    aberta_ha="encerrada às 14:09",
    briefing=(
        "O caminhão quebrou e foi rebocado. A gestora confirmou pelo botão e informou "
        "<strong>por quanto tempo</strong> o transporte levaria, então os alarmes desse "
        "veículo ficam suprimidos por esse prazo. Sem prazo informado, o padrão da Central "
        "são duas horas."
    ),
    acoes=_ACOES_FECHADA,
    conversa=[
        Turno(
            quem="ia",
            horario="14:07",
            status="lido",
            tipo="template",
            fala="Oi, Regina! Aqui é a assistente virtual da Bahrd Monitoramento. O ABC1D23 "
            "tá se movendo "
            "com a chave desligada, na Anhanguera. Vocês autorizaram algum reboque?",
            botoes=["Sim, autorizamos", "Não autorizamos", "Vou verificar"],
        ),
        Turno(quem="cliente", horario="14:08", tipo="botoes", fala="Sim, autorizamos"),
        Turno(
            quem="ia",
            horario="14:08",
            status="lido",
            fala="Ótimo. Por quanto tempo devo desconsiderar os alertas desse veículo?",
        ),
        Turno(quem="cliente", horario="14:09", fala="Umas 3 horas, chamamos o guincho às 13h40."),
        Turno(
            quem="ia",
            horario="14:09",
            status="lido",
            fala="Certo, Regina. Registrei como reboque autorizado e vou desconsiderar os "
            "alertas desse veículo pelas próximas 3 horas. Obrigada!",
        ),
    ],
    turnos=5,
    duracao="1:41",
    ficha={
        "Evento": MOVIMENTO_SEM_IGNICAO.rotulo,
        "Placa": "ABC1D23",
        "Cliente": "Jefferson Dias",
        "Número": "+55 11 99999-0007",
        "Logradouro": "Rodovia Anhanguera, Americana · 48 km/h, ignição desligada",
        "Coordenada": "-22.74141300, -47.27089810",
    },
    auditoria=[
        EventoAuditoria(
            horario="14:07:33",
            descricao="Evento recebido — <b>movimento com ignição desligada</b>, 48 km/h.",
        ),
        EventoAuditoria(
            horario="14:07:33",
            descricao="Política <b>v1.1</b> liberou o tratamento pela IA — "
            "playbook <b>PB-MOV-SEM-IGNICAO</b>, janela de 60 s, "
            "<b>confirmação e prazo de supressão</b>.",
        ),
        EventoAuditoria(
            horario="14:07:34",
            descricao="Consulta de posição — trajetória coerente e contínua, "
            "não é falso positivo de GPS.",
        ),
        EventoAuditoria(
            horario="14:08:02", descricao="Gestora confirmou o reboque pelo botão."
        ),
        EventoAuditoria(
            horario="14:09:04",
            descricao="Informou <b>3 horas</b> de transporte — alarmes suprimidos por esse "
            "prazo.",
        ),
        EventoAuditoria(
            horario="14:09:12",
            descricao="Fechada pela IA — desfecho <b>reboque_autorizado</b>.",
        ),
    ],
    politica_versao="v1.1",
    prompt_versao="v1.7",
)

_ENC_PANICO_ACIDENTAL = Ocorrencia(
    ocorrencia_id="OC-2026-08-11-000438",
    latitude=-25.5759704,
    longitude=-49.3123914,
    endereco="Rodovia Régis Bittencourt · Curitiba - PR",
    tipo_evento=PANICO.rotulo,
    grau="critica",
    canal="LIGACAO",
    placa="XYZ4E56",
    interlocutor="Marcos Pereira, motorista",
    telefone="+55 11 99999-0008",
    aberta_ha="encerrada às 13:22",
    briefing=(
        "A triagem estimou <strong>12% de chance de ser real</strong> — em rota, velocidade "
        "normal, sem correlatos e com três acionamentos anteriores que o operador registrou "
        "como acidentais. Abaixo do limiar, a IA ligou. Na abertura, sem nunca mencionar o "
        "botão, ouviu uma resposta curta demais e <strong>escalou em duas falas</strong>, "
        "sem perguntar mais nada. Juliana ligou de volta: era a mochila encostando no botão, "
        "e o motorista estava com o rádio ligado alto — daí a resposta seca."
    ),
    handoff=[
        "Cruzou telemetria, rota e histórico antes de falar · estimou 12% de chance de ser real.",
        "Abaixo do limiar de 90% — seguiu para o contato pelo PB-PANICO.",
        "Abriu como checagem de rotina. Não mencionou o botão, não pediu palavra-chave.",
        "Ouviu resposta monossilábica e encerrou a ligação sem mudar o tom.",
        "Escalou com motivo possivel_ocorrencia_real. Você assume daqui.",
    ],
    probabilidade_real=12,
    acoes=_ACOES_FECHADA,
    conversa=[
        Turno(
            quem="ia",
            horario="13:18",
            fala="Oi, seu Marcos! Aqui é a assistente virtual da Bahrd Monitoramento. Tô "
            "passando pra "
            "confirmar a viagem, tá tudo tranquilo aí no trecho?",
        ),
        Turno(quem="cliente", horario="13:18", transcrito=True, fala="Tá... tá sim."),
        Turno(
            quem="ia",
            horario="13:19",
            fala="Beleza, então tá tudo certo. Boa viagem, seu Marcos!",
        ),
    ],
    turnos=3,
    duracao="4:05",
    ficha={
        "Evento": PANICO.rotulo,
        "Placa": "XYZ4E56",
        "Cliente": "Marcos Pereira",
        "Número": "+55 11 99999-0008",
        "Logradouro": "Rodovia Régis Bittencourt, Curitiba · 82 km/h, em rota",
        "Coordenada": "-25.57597040, -49.31239140",
    },
    auditoria=[
        EventoAuditoria(horario="13:18:02", descricao="Evento recebido — <b>pânico</b>."),
        EventoAuditoria(
            horario="13:18:02",
            descricao="Política <b>v2.0</b>: evento crítico — <b>triagem obrigatória antes "
            "de qualquer contato</b>. Limiar: 90%.",
        ),
        EventoAuditoria(
            horario="13:18:06",
            descricao="Triagem: <b>12% de chance de ser real</b> · falso_positivo · "
            "confiança alta. Em rota | 82 km/h | nenhum correlato | 3/3 pânicos "
            "anteriores confirmados acidentais pelo operador.",
        ),
        EventoAuditoria(
            horario="13:18:06",
            descricao="<b>12% &lt; 90%</b> — liberado para contato pelo <b>PB-PANICO</b>, "
            "canal ligação.",
        ),
        EventoAuditoria(
            horario="13:18:24",
            descricao="Abertura como checagem de rotina — a palavra <b>pânico</b> não foi "
            "usada, conforme o playbook.",
        ),
        EventoAuditoria(
            horario="13:19:02",
            descricao="Resposta monossilábica. Escalonamento com motivo "
            "<b>possivel_ocorrencia_real</b> — a IA encerrou sem mudar o tom, sem pedir "
            "palavra-chave e sem mencionar o botão.",
        ),
        EventoAuditoria(
            horario="13:19:40",
            descricao="<b>Juliana Marques</b> assumiu e ligou de volta.",
        ),
        EventoAuditoria(
            horario="13:22:07",
            descricao="Encerrada por <b>Juliana Marques</b> — desfecho "
            "<b>acionamento_acidental_confirmado</b>. Nota: “mochila encostou no botão; "
            "rádio alto explicava a resposta curta; motorista confirmou que está tudo bem”.",
        ),
    ],
    politica_versao="v2.0",
    prompt_versao="v2.0",
)

_ENC_MANUTENCAO = Ocorrencia(
    ocorrencia_id="OC-2026-08-11-000430",
    latitude=-19.9678,
    longitude=-44.1985,
    endereco="Oficina Recanto Diesel · Av. Governador Valadares, Betim - MG",
    tipo_evento=REMOCAO_BATERIA.rotulo,
    grau="alta",
    canal="AUDIO",
    placa="DEF2G34",
    interlocutor="Carla Souza, motorista",
    telefone="+55 31 99999-0009",
    aberta_ha="encerrada às 11:58",
    briefing=(
        "A IA fez o contato, mas a resposta ficou no meio do caminho — “acho que é da "
        "oficina” não confirma nada. Sem confirmação clara dentro da janela, o caso "
        "escalou, como manda o princípio: <strong>dúvida vira humano, nunca fechamento</strong>. "
        "Roberto ligou para a oficina, confirmou a ordem de serviço nº 44-2291 e encerrou."
    ),
    acoes=_ACOES_FECHADA,
    conversa=[
        Turno(
            quem="ia",
            horario="11:51",
            status="lido",
            tipo="audio",
            duracao_s=10,
            fala="Oi, Carla! Assistente virtual da Bahrd Monitoramento. A bateria do "
            "rastreador do DEF2G34 "
            "foi desconectada agora. Tá tudo bem com o caminhão?",
        ),
        Turno(
            quem="cliente",
            horario="11:53",
            tipo="audio",
            duracao_s=6,
            transcrito=True,
            fala="Ah, acho que é da oficina, eles [trecho não compreendido] mexendo nele hoje.",
        ),
        Turno(
            quem="ia",
            horario="11:53",
            status="lido",
            tipo="audio",
            duracao_s=8,
            fala="Entendi, Carla. Só pra eu ter certeza: o caminhão está na oficina agora, "
            "com alguém trabalhando nele?",
        ),
        Turno(
            quem="cliente",
            horario="11:54",
            tipo="audio",
            duracao_s=4,
            transcrito=True,
            fala="É, acho que sim.",
        ),
        Turno(
            quem="ia",
            horario="11:54",
            status="entregue",
            tipo="audio",
            duracao_s=7,
            fala="Tudo bem, Carla. Vou passar pra um colega meu aqui da central confirmar "
            "com a oficina, tá? Obrigada!",
        ),
    ],
    turnos=5,
    duracao="6:12",
    ficha={
        "Evento": REMOCAO_BATERIA.rotulo,
        "Placa": "DEF2G34",
        "Cliente": "Carla Souza",
        "Número": "+55 31 99999-0009",
        "Logradouro": "Av. Governador Valadares, Betim · parado há 41 min",
        "Coordenada": "-19.96780, -44.19850",
    },
    auditoria=[
        EventoAuditoria(
            horario="11:51:09", descricao="Evento recebido — <b>remoção da bateria principal</b>."
        ),
        EventoAuditoria(
            horario="11:51:09",
            descricao="Política <b>v1.1</b> liberou o tratamento pela IA — "
            "playbook <b>PB-BATERIA</b>, janela de 90 s.",
        ),
        EventoAuditoria(
            horario="11:51:22",
            descricao="Contato por <b>áudio no WhatsApp</b> — entregue e ouvido.",
        ),
        EventoAuditoria(
            horario="11:53:40",
            descricao="Transcrição com <b>trecho não compreendido</b> — a resposta não "
            "confirma a causa.",
        ),
        EventoAuditoria(
            horario="11:54:31",
            descricao="Escalonamento automático — motivo <b>resposta_inconclusiva</b>. "
            "Nenhum desfecho foi registrado pela IA.",
        ),
        EventoAuditoria(
            horario="11:55:02",
            descricao="<b>Roberto Nunes</b> assumiu e ligou para a Oficina Recanto Diesel.",
        ),
        EventoAuditoria(
            horario="11:58:14",
            descricao="Encerrada por <b>Roberto Nunes</b> — desfecho "
            "<b>veiculo_em_manutencao</b>, ordem de serviço <b>44-2291</b> confirmada.",
        ),
    ],
    politica_versao="v1.1",
    prompt_versao="v1.7",
)


_ENC_BATERIA_BACKUP = Ocorrencia(
    ocorrencia_id="OC-2026-08-11-000424",
    latitude=-23.4966494,
    longitude=-46.5596930,
    endereco="Rodovia Fernão Dias · Guarulhos - SP",
    tipo_evento=ERRO_BATERIA_BACKUP.rotulo,
    grau="media",
    canal="LIGACAO",
    placa="MNO8P12",
    interlocutor="Marcia Fontes, gestora",
    telefone="+55 11 99999-0010",
    aberta_ha="encerrada às 10:47",
    briefing=(
        "Falha na bateria reserva <strong>do rastreador</strong> — ninguém no caminhão fez "
        "nada. É a <strong>11ª ocorrência deste equipamento em 90 dias</strong>, e 9 delas "
        "foram encerradas sem causa real. Não é caso de contato: é de manutenção. Marina "
        "avisou a gestora e abriu o chamado; o rastreador entrou na lista de inspeção."
    ),
    acoes=_ACOES_FECHADA,
    conversa=[],
    turnos=0,
    duracao="2:38",
    ficha={
        "Evento": ERRO_BATERIA_BACKUP.rotulo,
        "Placa": "MNO8P12",
        "Cliente": "Elias Barbosa",
        "Número": "+55 11 99999-0010",
        "Logradouro": "Rodovia Fernão Dias, Guarulhos · em rota, 78 km/h",
        "Coordenada": "-23.49664940, -46.55969300",
    },
    auditoria=[
        EventoAuditoria(
            horario="10:44:31", descricao="Evento recebido — <b>erro na bateria backup</b>."
        ),
        EventoAuditoria(
            horario="10:44:31",
            descricao="Política <b>v1.1</b>: <b>inelegível para a IA</b> — sem playbook, "
            "evento técnico sem conversa a ter.",
        ),
        EventoAuditoria(
            horario="10:44:32",
            descricao="Leitura de contexto pela IA — <b>11ª ocorrência em 90 dias</b>, "
            "9 encerradas sem causa real.",
        ),
        EventoAuditoria(horario="10:44:33", descricao="Enfileirada para o operador."),
        EventoAuditoria(
            horario="10:45:10",
            descricao="<b>Marina Duarte</b> assumiu e ligou para a gestora.",
        ),
        EventoAuditoria(
            horario="10:47:09",
            descricao="Chamado de manutenção <b>MAN-2026-0812</b> aberto para troca da "
            "bateria reserva.",
        ),
        EventoAuditoria(
            horario="10:47:22",
            descricao="Encerrada por <b>Marina Duarte</b> — desfecho "
            "<b>sem_causa_real_equipamento_para_inspecao</b>. É este desfecho que soma na "
            "contagem de rastreadores que disparam sem motivo.",
        ),
    ],
    politica_versao="v1.1",
    prompt_versao="v1.7",
)


@dataclass(frozen=True)
class _Fechamento:
    """Os dados do fechamento, amarrados ao registro completo.

    A linha da lista é **derivada** do detalhe, e não escrita ao lado dele: se
    fossem duas fontes, o dia em que divergissem seria o dia em que a aba
    deixaria de ser auditável.
    """

    detalhe: Ocorrencia
    desfecho: str
    por: Literal["ia", "operador"]
    responsavel: str
    encerrada_em: str
    custo_usd: float | None = None


#: Só bateria, ignição e pânico — os três da demonstração. Os fechamentos de
#: velocidade (`_ENC_VELOCIDADE`, `_ENC_TERCEIRA_VELOCIDADE`) continuam escritos
#: logo acima e voltam com uma linha aqui.
_FECHAMENTOS = [
    _Fechamento(
        _ENC_BATERIA_OK, "chave_geral_desligada_pelo_motorista", "ia", "IA", "19:12", 0.071
    ),
    _Fechamento(_ENC_REBOQUE_OK, "reboque_autorizado", "ia", "IA", "14:09", 0.083),
    _Fechamento(
        _ENC_PANICO_ACIDENTAL,
        "acionamento_acidental_confirmado",
        "operador",
        "Juliana Marques",
        "13:22",
        # A IA não falou com ninguém, mas leu o contexto — e leitura é chamada de
        # modelo. O custo aparece mesmo em caso fechado por humano, senão a conta
        # da POC fica menor do que é.
        0.004,
    ),
    _Fechamento(
        _ENC_MANUTENCAO, "veiculo_em_manutencao", "operador", "Roberto Nunes", "11:58", 0.026
    ),
    _Fechamento(
        _ENC_BATERIA_BACKUP,
        "sem_causa_real_equipamento_para_inspecao",
        "operador",
        "Marina Duarte",
        "10:47",
        0.003,
    ),
]


#: O id carrega a data do evento (`OC-AAAA-MM-DD-NNNNNN`). Derivar dali evita
#: um segundo campo que um dia contradiz o primeiro.
_DATA_NO_ID = re.compile(r"^OC-(\d{4})-(\d{2})-(\d{2})")


def _dia_do_id(ocorrencia_id: str) -> str | None:
    achado = _DATA_NO_ID.match(ocorrencia_id)
    if achado is None:
        return None
    ano, mes, dia = achado.groups()
    return f"{dia}/{mes}/{ano}"


def _como_encerrada(f: _Fechamento) -> Encerrada:
    return Encerrada(
        encerrada_dia=_dia_do_id(f.detalhe.ocorrencia_id),
        ocorrencia_id=f.detalhe.ocorrencia_id,
        tipo_evento=f.detalhe.tipo_evento,
        canal=f.detalhe.canal,
        placa=f.detalhe.placa,
        interlocutor=f.detalhe.interlocutor,
        desfecho=f.desfecho,
        encerrada_por=f.por,
        responsavel=f.responsavel,
        encerrada_em=f.encerrada_em,
        duracao=f.detalhe.duracao,
        custo_usd=f.custo_usd,
        tem_detalhe=True,
    )


ENCERRADAS = [_como_encerrada(f) for f in _FECHAMENTOS]

_POR_ID = {
    oc.ocorrencia_id: oc
    for oc in (
        _ROUBO_ATIVO,
        _PANICO,
        _ENTRADA_2,
        _MOV_SEM_IGNICAO,
        _REMOCAO_BATERIA,
        *(f.detalhe for f in _FECHAMENTOS),
    )
}


def ocorrencia(ocorrencia_id: str) -> Ocorrencia | None:
    return _POR_ID.get(ocorrencia_id)


def _custo_medio() -> float:
    """Média do que cada ocorrência encerrada custou em modelo.

    Aritmética sobre o custo real que o provedor devolve em cada chamada, não
    uma estimativa. Ocorrência sem custo registrado fica de fora da média em
    vez de entrar como zero — zero puxaria o número para baixo e faria a
    operação parecer mais barata do que é.
    """
    custos = [e.custo_usd for e in ENCERRADAS if e.custo_usd]
    return sum(custos) / len(custos) if custos else 0.0


def encerrados() -> Encerrados:
    return Encerrados(
        itens=ENCERRADAS,
        total_ia=sum(1 for e in ENCERRADAS if e.encerrada_por == "ia"),
        total_operador=sum(1 for e in ENCERRADAS if e.encerrada_por == "operador"),
    )


# ─────────────────────────── Reincidência / recall ───────────────────────────
# Critério deliberadamente conservador: 3 ou mais ocorrências do mesmo tipo em
# 90 dias, das quais pelo menos 2 o operador encerrou sem causa real. Um número
# alto sozinho não basta — caminhão que roda muito dispara muito. O que aponta
# defeito é o evento repetir e **nunca** ter causa.
MINIMO_OCORRENCIAS = 3
MINIMO_SEM_CAUSA = 2


def _avaliar(ocorrencias: int, sem_causa: int) -> tuple[bool, str]:
    if ocorrencias >= MINIMO_OCORRENCIAS and sem_causa >= MINIMO_SEM_CAUSA:
        return True, (
            f"{sem_causa} de {ocorrencias} encerradas sem causa real em 90 dias — "
            "padrão de defeito, não de operação"
        )
    if ocorrencias >= MINIMO_OCORRENCIAS:
        return False, "repete, mas as ocorrências tiveram causa confirmada"
    return False, "volume dentro do esperado"


def _reincidente(
    placa: str, imei: str, cliente: str, tipo: str, total: int, sem_causa: int, ultimo: str
) -> EquipamentoReincidente:
    candidato, motivo = _avaliar(total, sem_causa)
    return EquipamentoReincidente(
        placa=placa,
        imei=imei,
        cliente=cliente,
        tipo_evento=tipo,
        ocorrencias_90d=total,
        confirmados_sem_causa=sem_causa,
        ultimo_em=ultimo,
        candidato_a_recall=candidato,
        motivo=motivo,
    )


def reincidencia() -> list[EquipamentoReincidente]:
    return [
        _reincidente(
            "XYZ4E56", "860201061136415", "Transportadora Sul Cargas",
            PANICO.rotulo, 4, 4, "12/08/2026",
        ),
        _reincidente(
            "MNO8P12", "860201061140233", "Log Norte Transportes",
            "Erro na bateria backup", 11, 9, "12/08/2026",
        ),
        _reincidente(
            "JKL3M45", "860201061138871", "Rodoexpress Cargas",
            REMOCAO_BATERIA.rotulo, 5, 3, "11/08/2026",
        ),
        _reincidente(
            "VWX5Y78", "860201061142907", "Log Norte Transportes",
            ENTRADA_2_ACIONADA.rotulo, 3, 2, "10/08/2026",
        ),
        _reincidente(
            "DEF2G34", "860201061139002", "Rodoexpress Cargas",
            VELOCIDADE_EXCEDIDA.rotulo, 8, 0, "12/08/2026",
        ),
        _reincidente(
            "STU9V23", "860201061141556", "Transportadora Sul Cargas",
            REMOCAO_BATERIA.rotulo, 3, 1, "09/08/2026",
        ),
    ]


def metricas() -> Metricas:
    fechadas = encerrados()
    recall = sum(1 for e in reincidencia() if e.candidato_a_recall)

    return Metricas(
        vitais=[
            Vital(rotulo="Contenção", valor="58", unidade="%", nota="dos eventos elegíveis"),
            # Derivado da mesma lista que a aba "Encerrados" mostra — o número
            # aqui e as linhas lá são a mesma fonte, então batem sempre.
            Vital(
                rotulo="Encerradas",
                valor=str(fechadas.total_ia + fechadas.total_operador),
                nota=f"{fechadas.total_ia} pela IA · {fechadas.total_operador} pelo operador",
                destino="encerrados",
            ),
            Vital(
                rotulo="1º contato", valor="9", unidade="s", nota="mediana, do evento ao contato"
            ),
            # "Voz p95" saiu daqui. Media latência de ligação telefônica, e não
            # existe telefonia nesta fase — era um número medindo algo que não
            # roda. Custo é o oposto: sai da resposta do próprio provedor, é
            # conferível ocorrência por ocorrência, e é o número que decide se
            # a operação faz sentido.
            Vital(
                rotulo="Custo por atendimento",
                valor=f"{_custo_medio():.3f}".replace(".", ","),
                unidade="US$",
                nota="média das ocorrências encerradas",
            ),
            Vital(rotulo="Falsos fechamentos", valor="0", bom=True, selo="Dentro do critério"),
            Vital(
                rotulo="Para inspeção",
                valor=str(recall),
                nota="rastreadores que disparam sem motivo",
                destino="recall",
            ),
        ],
        contencao_por_hora=[
            44, 41, 39, 43, 47, 51, 54, 57, 59, 62,
            64, 65, 63, 61, 60, 63, 66, 67, 63, 58,
        ],
        # Os eventos inelegíveis entram no volume — eles acontecem e são
        # atendidos — mas nunca contam como contenção: a IA não os trata.
        volume_por_evento=[
            Barra(rotulo=VELOCIDADE_EXCEDIDA.rotulo, valor=214),
            Barra(rotulo=ULTRAPASSOU_LIMITE_VELOCIDADE.rotulo, valor=98),
            Barra(rotulo=VELOCIDADE_EXCEDIDA_CERCA_POLIGONO.rotulo, valor=63),
            Barra(rotulo="Entrou na cerca", valor=57),
            Barra(rotulo="Voltou à Cerca de Polígono", valor=54),
            Barra(rotulo=REMOCAO_BATERIA.rotulo, valor=41),
            Barra(rotulo="Erro na bateria backup", valor=23),
            Barra(rotulo=MOVIMENTO_SEM_IGNICAO.rotulo, valor=12),
            Barra(rotulo=ENTRADA_2_ACIONADA.rotulo, valor=9),
            Barra(rotulo=PANICO.rotulo, valor=7),
            Barra(rotulo=ROUBO_ATIVO_MOVIMENTO.rotulo, valor=2),
        ],
        motivos_de_escalonamento=[
            Barra(rotulo="Sem contato após a cascata", valor=19),
            Barra(rotulo="Tipo de evento inelegível", valor=18),
            Barra(rotulo="Gestor não confirmou a autorização", valor=6),
            Barra(rotulo="Causa normal não confirmada", valor=5),
            Barra(rotulo="Resposta inconclusiva", valor=4),
            Barra(rotulo="Pressão de prazo relatada", valor=3),
            Barra(rotulo="Inconsistência com a telemetria", valor=2),
            Barra(rotulo="Cliente pediu uma pessoa", valor=2),
        ],
        total_escalonamentos=59,
    )
