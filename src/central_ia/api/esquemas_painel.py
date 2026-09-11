"""Contratos da API do painel.

Estes esquemas são o **contrato** entre o back-end e o painel. Eles não mudam
quando o orquestrador real entrar no Sprint 2 — o que muda é a origem dos
dados, hoje em :mod:`central_ia.api.amostra`.

É por isso que o painel pode ser construído e testado agora sem virar
retrabalho: o front-end programa contra este contrato, não contra a amostra.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Grau = Literal["critica", "alta", "media", "baixa"]
Quem = Literal["ia", "cliente"]

# O canal muda como a conversa é EXIBIDA, não só por onde ela passou.
# Ligação é transcrição; WhatsApp é troca de mensagens, e o operador precisa
# ver o que o cliente viu — inclusive os botões que ele teve para tocar.
Canal = Literal["LIGACAO", "AUDIO", "TEXTO"]


class PassoRoteiro(BaseModel):
    """Um passo da narração do que a IA está fazendo.

    A narração vem do **estado da máquina**, nunca do modelo: estado da
    ocorrência + passo do playbook + ferramenta em execução. Se o LLM
    escrevesse isto, o painel poderia mentir sobre o que a IA fez.
    """

    frase: str
    duracao_s: int = Field(description="Quanto tempo o passo dura, para a simulação da tela")
    falando: bool = Field(description="A IA está falando agora, ou esperando?")


class Turno(BaseModel):
    """Um turno da conversa.

    Os campos além de `quem`/`fala` existem porque no WhatsApp o operador
    precisa ver a mensagem como ela foi entregue: o horário, os botões que o
    cliente teve para tocar, se a nota de voz foi ouvida, e — o mais
    importante — se o texto foi **digitado ou transcrito**.
    """

    quem: Quem
    fala: str
    horario: str | None = Field(default=None, description="HH:MM, como aparece no WhatsApp.")
    tipo: Literal["texto", "audio", "botoes", "template"] = "texto"
    duracao_s: int | None = Field(default=None, description="Duração da nota de voz, em segundos.")
    botoes: list[str] = Field(default=[], description="Botões oferecidos junto com a mensagem.")
    status: Literal["enviado", "entregue", "lido"] | None = Field(
        default=None, description="Confirmação de entrega. Só em mensagem que a IA enviou."
    )
    transcrito: bool = Field(
        default=False,
        description="O texto veio de STT, não foi digitado. O operador precisa saber: "
        "transcrição erra, e ele pode estar lendo algo que o cliente não disse.",
    )


class ItemFila(BaseModel):
    ocorrencia_id: str
    grau: Grau
    tipo_evento: str
    canal: Canal
    placa: str
    interlocutor: str
    nota: str | None = None

    #: `link` (evento real) ou `teste` (disparado pela tela do painel).
    #:
    #: ⛔ **Sem isto a tela de eventos de teste vira fonte de incidente.** Um
    #: pânico disparado para experimentar fica na mesma fila, com a mesma cara,
    #: do pânico de um motorista, e quem está de plantão pode acionar apoio por
    #: causa de um teste.
    #:
    #: Opcional para o contrato não quebrar com quem já consome a fila.
    origem: str | None = None

    # Segundos decorridos e janela do tipo de evento. Continuam no contrato
    # porque são a janela da política e valem para o motor — mas o painel
    # deixou de mostrá-los: prioridade quem dá é o `grau`, e um cronômetro por
    # linha competia por atenção sem mudar a ordem do trabalho.
    decorrido_s: int
    sla_s: int

    # Quando o evento aconteceu. É o que a tela mostra ao lado de cada item:
    # pergunta de registro, de conferência com o cliente e de relatório.
    momento: str | None = Field(default=None, description="HH:MM do evento.")
    dia: str | None = Field(
        default=None,
        description="DD/MM/AAAA do evento. O ano é obrigatório: a base da Bahrd "
        "tem registro antigo, e data sem ano num relatório de 90 dias que "
        "atravessa o réveillon vira dúvida na hora errada.",
    )
    momento_completo: str | None = Field(
        default=None, description="Data e hora completas, para o tooltip e a conferência."
    )

    # Mesma posição que a tela de ocorrência usa. Está aqui porque a tela ao
    # vivo lê do item da fila, não da ocorrência — e quem acompanha um
    # atendimento em curso precisa ver onde o caminhão está tanto quanto quem
    # abre o caso depois.
    latitude: float | None = None
    longitude: float | None = None
    endereco: str | None = None

    # Contexto extra que só aparece na fila humana
    leitura_ia: str | None = Field(
        default=None,
        description="Leitura de contexto em evento que nunca vai para a IA (pânico). "
        "Informativa, nunca prescritiva.",
    )
    tratamento_paralelo: str | None = Field(
        default=None,
        description="O que a IA está tentando em paralelo, quando o caso pode sair da fila humana.",
    )

    tem_detalhe: bool = False
    tem_ao_vivo: bool = False

    #: A conversa está acontecendo AGORA, com uma pessoa de verdade.
    #:
    #: Muda como a tela ao vivo se comporta. Na amostra, as falas aparecem uma a
    #: cada 3 s para simular o ritmo de um atendimento. Numa conversa real isso
    #: seria mentira e atraso: as mensagens já foram trocadas, e segurá-las faz
    #: o operador achar que a IA travou.
    ao_vivo_real: bool = False
    roteiro: list[PassoRoteiro] = []
    falas: list[Turno] = []


class Fila(BaseModel):
    precisa_de_voce: list[ItemFila]
    ia_esta_fazendo: list[ItemFila]


class EventoAuditoria(BaseModel):
    horario: str
    descricao: str = Field(description="Pode conter <b> para destacar o termo decisivo.")


class Ocorrencia(BaseModel):
    ocorrencia_id: str
    tipo_evento: str
    grau: Grau
    canal: Canal
    placa: str
    interlocutor: str
    telefone: str | None = Field(
        default=None,
        description="Número do interlocutor, como aparece no cabeçalho do chat. "
        "É operacional: é para onde a mensagem foi, e para onde o operador liga.",
    )
    aberta_ha: str

    # Onde o veículo estava no momento do evento. O painel desenha um mini-mapa
    # a partir daqui e oferece o link para o mapa real. Opcional de propósito:
    # evento sem posição existe (rastreador mudo é justamente um dos casos), e
    # nesse caso o mapa some em vez de mostrar um ponto inventado.
    latitude: float | None = None
    longitude: float | None = None
    endereco: str | None = Field(
        default=None, description="Endereço aproximado, como a plataforma devolve."
    )

    briefing: str = Field(description="O que a IA apurou, em 3 ou 4 frases.")
    handoff: list[str] = Field(
        default=[],
        description="O que a IA fez antes de o caso chegar aqui, em frases curtas. "
        "A trilha de auditoria tem tudo, mas vem fechada e é longa; quem recebe "
        "um caso crítico precisa entender em cinco segundos o que já foi feito, "
        "senão refaz do zero e o tempo que a triagem economizou volta a ser gasto.",
    )
    probabilidade_real: int | None = Field(
        default=None,
        description="Chance de o caso ser real, estimada pela triagem. Só existe "
        "em evento crítico.",
    )
    acoes: list[str] = Field(description="Ações disponíveis ao operador, na ordem de recomendação.")

    conversa: list[Turno]
    turnos: int
    duracao: str

    ficha: dict[str, str] = Field(description="Cliente, veículo, motorista, posição, rota, carga.")

    auditoria: list[EventoAuditoria]
    politica_versao: str
    prompt_versao: str


class Encerrada(BaseModel):
    """Ocorrência já resolvida — pela IA ou pelo operador.

    O painel precisa mostrar o que a IA fechou, e não só o que sobrou para o
    humano. Sem isso, o operador vê metade da operação e a contenção vira um
    número que ninguém consegue conferir.
    """

    ocorrencia_id: str
    tipo_evento: str
    canal: Canal
    placa: str
    interlocutor: str
    desfecho: str
    encerrada_por: Literal["ia", "operador"]
    responsavel: str = Field(
        description="Quem assinou o fechamento: 'IA' ou o nome do operador. "
        "O nome importa — 'operador' é um papel, e quem responde por um "
        "fechamento é uma pessoa com nome, localizável depois."
    )
    encerrada_em: str = Field(description="HH:MM")
    encerrada_dia: str | None = Field(
        default=None,
        description="DD/MM/AAAA do encerramento. Sem data, uma lista que mistura "
        "registro antigo com o de hoje só mostra horas soltas.",
    )
    duracao: str
    custo_usd: float | None = None
    tem_detalhe: bool = Field(
        default=False,
        description="Existe registro completo para abrir. Na amostra a maioria é só "
        "linha de histórico; as ocorrências simuladas nesta sessão têm o caso inteiro. "
        "O painel não oferece um clique que leva a 404.",
    )


class Encerrados(BaseModel):
    itens: list[Encerrada]
    total_ia: int
    total_operador: int


class EquipamentoReincidente(BaseModel):
    """Equipamento que repete o mesmo evento — candidato a inspeção.

    A contagem é **aritmética sobre o desfecho que o operador registrou**, sem
    modelo nenhum no caminho. Isso importa: sugerir recall de equipamento com
    base em inferência de IA seria trocar um problema de manutenção por uma
    aposta. Aqui o número é conferível linha a linha.
    """

    placa: str
    imei: str
    cliente: str | None = None
    tipo_evento: str
    ocorrencias_90d: int
    confirmados_sem_causa: int = Field(
        description="Quantas o operador encerrou como acidental ou sem causa real."
    )
    ultimo_em: str
    candidato_a_recall: bool
    motivo: str


class Vital(BaseModel):
    rotulo: str
    valor: str
    unidade: str | None = None
    nota: str | None = None
    bom: bool = False
    selo: str | None = None
    destino: Literal["recall", "encerrados"] | None = Field(
        default=None,
        description="Para onde o número leva quando clicado. Só os vitais que "
        "têm detalhamento recebem destino — dar aparência de clique a um número "
        "que não abre nada ensina o operador a desconfiar da tela.",
    )


class Barra(BaseModel):
    rotulo: str
    valor: int


class Metricas(BaseModel):
    vitais: list[Vital]
    contencao_por_hora: list[int] = Field(
        description="00h..19h, em % de eventos elegíveis contidos."
    )
    volume_por_evento: list[Barra]
    motivos_de_escalonamento: list[Barra]
    total_escalonamentos: int
