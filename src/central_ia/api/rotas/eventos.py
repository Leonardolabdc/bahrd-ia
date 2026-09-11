"""Entrada de evento real da plataforma da Bahrd.

    sistema da Bahrd → POST /eventos/link → política → triagem → IA → WhatsApp

É o outro lado do `whatsapp.py`. Lá a conversa começa porque **uma pessoa
escreveu**; aqui começa porque **um caminhão fez alguma coisa** — e é este o
fluxo de produção. A palavra-chave `bateria` era o andaime que permitiu
demonstrar sem depender da TI.

Três decisões que o formato de origem obriga:

1. **A assinatura é opcional enquanto o segredo não existe.** Sem
   `BAHRD_WEBHOOK_HMAC_SECRET`, aceita e avisa no log — é o que deixa testar com
   Postman hoje. Mesma escolha do token do painel, e pela mesma razão: trancar
   antes de haver com quem combinar a chave só impede o teste.
2. **Sem telefone não há contato.** O payload traz `contato_telefone`, mas ele
   pode vir vazio. Abrir ocorrência sem para quem escrever geraria caso que
   nasce órfão — melhor registrar e devolver 200.
3. **Fora do catálogo nunca vira atendimento automático.** A regra é a mesma do
   pipeline; repeti-la aqui é deliberado, porque este é o ponto de entrada.

Sempre devolve **200 quando a assinatura confere**, mesmo em falha nossa. Quem
dispara webhook trata erro HTTP como endpoint quebrado e reduz as entregas —
vale para a Meta, vale para a Bahrd.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import NamedTuple

from fastapi import APIRouter, Request, Response, status

from central_ia.api.rotas.whatsapp import (
    _triar,
    anotar_mensagem_enviada,
    vigiar_silencio_apos_template,
)
from central_ia.config import Settings, settings
from central_ia.domain import eventos
from central_ia.integrations.mensageria import (
    modelos,
    numero_autorizado,
    variantes_do_numero,
)
from central_ia.integrations.mensageria.meta import (
    ClienteMeta,
    MetaIndisponivel,
    parametro_seguro,
)
from central_ia.integrations.rastreamento import construir_fonte
from central_ia.integrations.rastreamento.bahrd import FUSO_BAHRD
from central_ia.integrations.rastreamento.bahrd_webhook import (
    PayloadInvalido,
    parse_evento_webhook,
)
from central_ia.observability.logging import logger
from central_ia.observability.tracing import Identificacao, marcar_notificacao
from central_ia.orchestration import numeros_removidos
from central_ia.orchestration.sessao_whatsapp import SESSOES, Sessao

log = logger(__name__)

router = APIRouter(prefix="/eventos", tags=["eventos"])

#: Cabeçalho combinado com a TI da Bahrd. Ainda não confirmado — ver doc 08.
CABECALHO_ASSINATURA = "X-Assinatura"

#: O modelo que serve **qualquer** evento, e a variante com mapa.
#:
#: Quatro parâmetros, nesta ordem: **rótulo do evento, placa, horário, local**.
#: Aprovados na Meta em 26/08/2026.
#:
#: **O tipo do evento virou parâmetro.** Antes cada evento tinha o seu texto,
#: com "Remoção da bateria principal" escrito dentro; agora é `{{1}}`, e os
#: onze tipos do catálogo cabem no mesmo modelo. Evento novo deixou de custar
#: um modelo e uma espera de aprovação.
#:
#: O nome do contato não entra: o texto não cumprimenta ninguém. A IA usa o
#: nome depois, na conversa, onde ela pode escrever com naturalidade.
#: ⚠️ **Cada um tem um par que chama a pessoa pelo nome**, desde 10/09/2026.
#: `contato_nome` é opcional no payload e a Meta recusa parâmetro vazio, então
#: sem nome a rota cai para o modelo sem nome, que abre só com a saudação.
class ModelosDoEvento(NamedTuple):
    """Os modelos de um evento: a geração em uso e a reserva, com e sem mapa.

    ⛔ **A reserva não é sobra, é a rede.** Um modelo novo passa horas em
    análise na Meta, e pode ser reprovado ou pausado por qualidade depois. A
    reserva é a geração anterior, já aprovada e já provada em produção — é para
    ela que a cadeia cai enquanto a nova não vale, e é por isso que um modelo
    novo entra sozinho, sem deploy e sem nenhuma janela sem notificação.

    ⚠️ **As duas gerações têm contagens de parâmetro diferentes**, e é por isso
    que `templates_do_evento` monta duas listas: a nova leva a abertura na
    frente, a reserva não a tem.
    """

    mapa: str
    texto: str
    mapa_reserva: str
    texto_reserva: str


#: Os modelos que servem bateria e movimento — e qualquer tipo do catálogo, já
#: que o tipo do evento entra como parâmetro em vez de virar modelo novo.
MODELOS_DE_ALERTA = ModelosDoEvento(
    mapa="evento_alerta_pergunta_mapa",
    texto="evento_alerta_pergunta",
    mapa_reserva="evento_alerta_mapa",
    texto_reserva="evento_alerta",
)

#: Nomes soltos, para quem só precisa citar um. A fonte é a tupla acima.
TEMPLATE_ALERTA = MODELOS_DE_ALERTA.texto_reserva
TEMPLATE_ALERTA_MAPA = MODELOS_DE_ALERTA.mapa_reserva


#: O primeiro nome, quando o payload traz `contato_nome`. `""` quando não traz.
#:
#: ⚠️ **Só o primeiro.** O cadastro traz `"Antônio da Silva, Transportes X"`, e
#: o campo inteiro daria *"Olá, bom dia, Antônio da Silva, Transportes X!"*.
#: Mesmo corte de `whatsapp._primeiro_nome`.
def primeiro_nome_do_contato(evento) -> str:
    bruto = (getattr(evento, "motorista", None) or "").strip()
    return bruto.split(",")[0].split(" ")[0].strip()


#: A saudação pela hora do evento, no fuso de quem vai ler.
#:
#: ⚠️ **Pela hora do EVENTO, não pela hora de agora.** São a mesma coisa em
#: produção, onde a notificação sai em segundos — mas não num reprocessamento
#: nem num disparo atrasado, e ali "boa noite" num evento das 10h da manhã
#: denuncia a máquina mais do que não cumprimentar.
#:
#: Os cortes são os do português falado, não os do relógio: a tarde começa ao
#: meio-dia e a noite às 18h. Antes das 5h ainda é "boa noite" — quem dirige de
#: madrugada não recebe "bom dia" às 3h.
#:
#: Minúscula porque cai depois de vírgula: *"Olá, bom dia, Geraldo!"*.
def saudacao_do_evento(evento) -> str:
    hora = evento.momento.astimezone(FUSO_BAHRD).hour
    if 5 <= hora < 12:
        return "bom dia"
    if 12 <= hora < 18:
        return "boa tarde"
    return "boa noite"


#: A abertura inteira: saudação e, quando houver, o primeiro nome.
#:
#: ⛔ **Um parâmetro só, e não dois.** Saudação e nome viajam juntos porque o
#: nome é opcional e a Meta recusa parâmetro vazio: com duas variáveis seriam
#: precisos dois modelos, um para cada caso, e a conta dobraria a cada campo
#: opcional novo. Com um, o mesmo modelo serve *"bom dia, Geraldo"* e
#: *"bom dia"*, e a frase fecha certo nos dois.
#:
#: Foi isto que aposentou as variantes `_nome`, criadas poucas horas antes na
#: mesma manhã de 10/09/2026 — elas existiam só para resolver o nome ausente.
def abertura_do_evento(evento) -> str:
    nome = primeiro_nome_do_contato(evento)
    saudacao = saudacao_do_evento(evento)
    return f"{saudacao}, {nome}" if nome else saudacao


#: Eventos com modelo próprio, `codigo -> (sem nome, com nome)`.
#:
#: Os modelos apontados aqui recebem **a placa**, mais o primeiro nome quando
#: ele existe — e nada além disso. É a diferença que importa: o alerta nomeia o
#: evento, cita horário e logradouro; estes não citam nenhum dos três.
#:
#: A cadeia de tentativas é a mesma dos outros, inclusive com cartão de mapa.
#:
#: ⛔ **O pânico voltou para cá em 10/09/2026, e o motivo é o `PB-PANICO`.**
#: Ele saiu daqui em 02/09 para usar o `evento_alerta`, que nomeia o evento em
#: `{{1}}` — e o rótulo do PANICO no catálogo é, literalmente, `"Pânico"`.
#: A palavra que o playbook proíbe ia impressa para o celular do cliente:
#:
#:     "Você nunca diz que houve um pânico. Não fala em equipamento de
#:      emergência, não fala em alerta, não fala em pânico (...) Nada de
#:      'preciso confirmar uma coisa'. É uma checagem de rotina. Nada mais."
#:
#: Se o alerta foi real, quem estiver junto do motorista passa a saber que a
#: central percebeu — e é exatamente isso que não pode acontecer. O texto novo
#: do `evento_alerta` ("Identificamos uma ocorrência... precisamos confirmar
#: uma informação") seria a segunda violação na mesma mensagem.
#:
#: Por isso o modelo do pânico não tem nome de evento, horário, local nem mapa.
#: Sobra a placa e uma pergunta de rotina. O cartão saiu junto porque a posição
#: atual também diz "estamos te vendo agora".
#:
#: ⚠️ **A pendência dos botões continua de pé.** O `evento_panico` levava só
#: "Ligar 0800"; agora leva "Preciso de ajuda!" e "Está tudo bem!" — e o
#: segundo é o que alguém sob coação tocaria com o assaltante olhando (doc 17).
#: Botão de telefone não devolve webhook, então manter o 0800 deixaria a IA sem
#: saber que o cliente respondeu e a janela de 24 h fechada. O que segura o
#: risco hoje é a triagem, não o template: acima de `LIMIAR_ESCALONAMENTO` a IA
#: não conduz nem encerra, e um "Está tudo bem!" sozinho não fecha caso nenhum.
#: **É mitigação, não solução**, e a decisão de quais botões o pânico leva
#: continua sendo dos gestores da Central.
TEMPLATE_PROPRIO: dict[str, ModelosDoEvento] = {
    "PANICO": ModelosDoEvento(
        mapa="evento_panico_saudacao_mapa",
        texto="evento_panico_saudacao",
        mapa_reserva="evento_panico_mapa",
        texto_reserva="evento_panico",
    )
}


#: Quais eventos disparam notificação para o cliente.
#:
#: **Está explícito de propósito.** Antes a lista era efeito colateral de
#: quais eventos tinham modelo, e agora o modelo serve todos — sem esta trava,
#: a troca de 26/08 faria clientes começarem a receber mensagem de velocidade
#: excedida, que eles nunca receberam. Quais eventos falam com o cliente é
#: decisão de operação, não consequência de refatoração.
#:
#: Sete tipos são `elegivel_ia`; três notificam. Acrescentar é uma linha aqui.
EVENTOS_QUE_NOTIFICAM: frozenset[str] = frozenset(
    {"REMOCAO_BATERIA", "MOVIMENTO_SEM_IGNICAO", "PANICO"}
)


#: **Removido em 10/09/2026.** Existia o `LOCAL_NO_MAPA = "veja o mapa acima"`:
#: quando o evento vinha sem endereço, o cartão de mapa mostrava a coordenada e
#: o corpo da mensagem mandava o motorista olhar o cartão. A intenção era boa —
#: dois números negativos não são endereço para quem está dirigindo.
#:
#: ⛔ **Mas fazia o cartão e o corpo dizerem coisas diferentes sobre o mesmo
#: ponto**, e foi isso que motivou a troca: o pedido é que o endereço da
#: mensagem seja o do evento real e seja o mesmo texto do cartão, sempre.
#: Agora os dois chamam `local_do_evento`, e não há segunda cascata que possa
#: divergir da primeira.
#:
#: O dia em que a Bahrd mandar `endereco` no payload, este degrau some sozinho —
#: é o pedido de melhor retorno da lista do doc 08.


def localizacao_do_evento(evento) -> dict[str, str] | None:
    """O bloco de mapa da Meta, ou `None` quando não dá para montar.

    `None` é o sinal para `templates_do_evento` nem oferecer a variante com
    mapa. **Modelo com cabeçalho de localização exige o bloco preenchido**, e
    mandar sem ele faz a Meta recusar — o motorista não receberia o mapa *nem o
    aviso do alarme*.

    Perder o mapa é chato. Perder a notificação é grave.
    """
    if evento.latitude is None or evento.longitude is None:
        return None

    # ⚠️ `address` é OBRIGATÓRIO, não opcional. Descoberto em 27/08/2026 no
    # primeiro disparo real: a Meta devolveu «Parameter 'address' is mandatory
    # for component parameter type 'location'» e o modelo com mapa falhou.
    #
    # Enviá-lo só quando havia endereço parecia razoável e era o pior caso
    # possível: **a Bahrd não manda `endereco`**, então o mapa falhava sempre e
    # a notificação saía sempre pela reserva de texto. O mapa nunca teria
    # funcionado em produção, e o sintoma era um aviso de `template_falhou` no
    # log, com a mensagem chegando bonitinha ao cliente.
    return {
        "latitude": str(evento.latitude),
        "longitude": str(evento.longitude),
        # Vira o título do cartão. A placa é o que o motorista reconhece.
        "name": evento.veiculo,
        # ⛔ **A MESMA função que preenche o `Local:` do corpo.** Foi pedido
        # explícito em 10/09/2026: o endereço do cartão e o da mensagem têm que
        # ser o mesmo texto, sempre. Antes eram duas cascatas parecidas escritas
        # em lugares diferentes, e elas divergiam no último degrau — o cartão
        # mostrava a coordenada e o corpo mandava "veja o mapa acima".
        #
        # A garantia aqui é estrutural, não de disciplina: não há como as duas
        # discordarem porque não há duas. Copiar a cascata para cá de novo,
        # "para não depender de outra função", recria exatamente o defeito.
        "address": local_do_evento(evento),
    }


#: Texto do `Local:` quando nada melhor existe. Precisa existir: a Meta rejeita
#: parâmetro de template vazio, e o envio inteiro falharia por causa disso.
LOCAL_DESCONHECIDO = "não informado"


def local_do_evento(evento) -> str:
    """O `Local:` da notificação, na melhor forma disponível.

    Em cascata porque a origem varia. O webhook da Bahrd hoje manda só
    coordenada; o export em XLS traz endereço; a cerca aparece em alguns
    eventos. Escrever "-25.4504, -49.2562" para um motorista é ruim, e ainda
    assim é melhor que não dizer onde o caminhão está — ele consegue conferir
    no app, que é justamente o que a mensagem pede.

    Some no dia em que a Bahrd incluir `endereco` no payload. É o pedido de
    melhor retorno da lista do doc 08, junto com o `id` próprio.
    """
    if evento.endereco:
        return evento.endereco
    if evento.objeto_geografico:
        return evento.objeto_geografico
    if evento.latitude is not None and evento.longitude is not None:
        return f"{evento.latitude:.5f}, {evento.longitude:.5f}"
    return LOCAL_DESCONHECIDO


def horario_do_evento(evento) -> str:
    """`18:30` — a hora do evento no fuso de quem vai ler.

    ⚠️ **A conversão não é enfeite.** `EventoRastreamento.momento` é **UTC**:
    o `bahrd_webhook` recebe hora de Brasília sem fuso e converte na entrada,
    que é o certo para guardar e comparar. Formatar direto daria `21:30` para
    um evento das 18:30 — três horas de erro na tela do motorista, e ele
    concluindo que o alarme é de outro momento.

    Não aparece em desenvolvimento: a máquina está em Brasília e o erro fica
    escondido atrás do fuso do sistema. Aparece em produção, onde o contêiner
    roda em UTC.
    """
    return evento.momento.astimezone(FUSO_BAHRD).strftime("%H:%M")


def templates_do_evento(tipo, evento) -> list[tuple[str, list[str], dict[str, str] | None]]:
    """Os modelos a tentar, em ordem de preferência: `(nome, parâmetros, mapa)`.

    **Lista, e não escolha única, porque a notificação precisa sair.** Um
    modelo pode falhar por motivo que não dá para prever daqui: ainda em
    análise, reprovado depois, pausado por qualidade. Em qualquer desses casos
    a próxima tentativa entrega o aviso do alarme.

    Perder o mapa é chato. Perder a saudação é irrelevante. Perder a
    notificação é grave — e é essa escala que define a ordem:

        1. geração nova, com mapa
        2. reserva, com mapa           (a nova ainda não vale)
        3. geração nova, sem mapa      (não há coordenada)
        4. reserva, sem mapa           (a última instância)

    ⛔ **É esta cadeia que faz um modelo novo entrar sozinho em produção.**
    Enquanto a Meta analisa, o envio da geração nova falha e a reserva entrega
    a mensagem; no instante em que for aprovada, ela passa a valer sem ninguém
    mexer em nada. Foi assim que as variantes com nome entraram em 10/09/2026,
    e no mesmo dia a geração com saudação — sem nenhuma janela sem notificação.

    O que muda de um evento para outro não é a cadeia, são duas coisas: **quais
    modelos** e **quais parâmetros comuns**. O pânico tem os seus porque o
    `PB-PANICO` proíbe nomear o evento — ver `TEMPLATE_PROPRIO`.

    Vazia quando o evento não notifica — ver `EVENTOS_QUE_NOTIFICAM`.
    """
    if tipo.codigo not in EVENTOS_QUE_NOTIFICAM:
        return []

    proprio = TEMPLATE_PROPRIO.get(tipo.codigo)
    if proprio is not None:
        modelos, comuns = proprio, [evento.veiculo]
    else:
        modelos = MODELOS_DE_ALERTA
        comuns = [
            tipo.rotulo,
            evento.veiculo,
            horario_do_evento(evento),
            local_do_evento(evento),
        ]

    mapa = localizacao_do_evento(evento)
    # A geração nova leva a abertura na frente; a reserva não tem esse campo.
    com_abertura = [abertura_do_evento(evento), *comuns]
    tentativas: list[tuple[str, list[str], dict[str, str] | None]] = []

    if mapa is not None:
        tentativas.append((modelos.mapa, com_abertura, mapa))
        tentativas.append((modelos.mapa_reserva, comuns, mapa))
    tentativas.append((modelos.texto, com_abertura, None))
    tentativas.append((modelos.texto_reserva, comuns, None))
    return tentativas


def assinatura_confere(segredo: str, corpo: bytes, enviada: str) -> bool:
    """HMAC-SHA256 do corpo bruto, no mesmo formato que a Meta usa.

    Escolhido por ser o que já implementamos duas vezes e a TI provavelmente
    conhece. Se eles preferirem token fixo no cabeçalho, muda só esta função.
    """
    limpa = enviada.removeprefix("sha256=")
    esperada = hmac.new(segredo.encode("utf-8"), corpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperada, limpa)


def _autorizado(cfg: Settings, request: Request, corpo: bytes) -> bool:
    """Sem segredo configurado, aceita — e **avisa**.

    O aviso importa: endpoint aberto é aceitável enquanto o dado é fictício, e
    deixa de ser no dia do primeiro evento real. O log é o que impede isso de
    passar despercebido.
    """
    if cfg.bahrd_webhook_hmac_secret is None:
        log.warning("eventos_link_sem_assinatura", motivo="BAHRD_WEBHOOK_HMAC_SECRET ausente")
        return True

    enviada = request.headers.get(CABECALHO_ASSINATURA, "")
    if not enviada:
        log.warning("eventos_link_sem_cabecalho_de_assinatura")
        return False

    return assinatura_confere(
        cfg.bahrd_webhook_hmac_secret.get_secret_value(), corpo, enviada
    )


@router.post(
    "/link",
    summary="Recebe um evento de rastreamento da plataforma da Bahrd",
    description=(
        "O sistema da Bahrd dispara um POST aqui quando o evento acontece. "
        "Formato acordado em `a documentação interna do projeto`."
    ),
)
async def entrada_link(request: Request) -> Response:
    cfg = settings()
    corpo = await request.body()

    # ── 1. Assinatura, antes de olhar o conteúdo ────────────────────────────
    if not _autorizado(cfg, request, corpo):
        log.warning("eventos_link_assinatura_invalida")
        return Response(status_code=status.HTTP_403_FORBIDDEN)

    # `UnicodeDecodeError` também: `json.loads` sobre bytes tenta decodificar
    # como UTF-8 antes de olhar a sintaxe, e um payload em latin-1 — que é o
    # que muitos sistemas no Brasil ainda mandam — levanta essa, não a de JSON.
    # Sem capturar as duas, "Veículo" com acento errado vira **500**, e 500 faz
    # quem dispara marcar o endpoint como quebrado.
    try:
        payload = json.loads(corpo or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError) as erro:
        log.warning("eventos_link_corpo_ilegivel", erro=str(erro))
        return _resposta(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            erro="corpo não é JSON válido em UTF-8",
        )

    resultado = await processar_evento_link(cfg, payload)
    return _resposta(resultado.http, **resultado.corpo)


# ─────────────────────────── o fluxo, sem HTTP ───────────────────────────


@dataclass(frozen=True, slots=True)
class ResultadoDoEvento:
    """O que aconteceu com um evento, antes de virar resposta HTTP.

    `corpo` é o JSON exato que a Bahrd recebe, montado aqui e não no chamador:
    o contrato dela é por chave presente, não só por valor, e um `motivo: null`
    a mais numa resposta de sucesso é mudança de contrato silenciosa.

    `sessao` é o extra que só o painel usa. Quem responde webhook não tem o que
    fazer com ela, e quem disparou um teste precisa dela para linkar a
    ocorrência no recibo.
    """

    http: int
    corpo: dict[str, object] = field(default_factory=dict)
    sessao: object | None = None

    @property
    def atendido(self) -> bool:
        return bool(self.corpo.get("atendido"))

    @property
    def motivo(self) -> str | None:
        valor = self.corpo.get("motivo")
        return valor if isinstance(valor, str) else None


def _recusa(motivo: str) -> ResultadoDoEvento:
    """200 com `atendido: false`, que é o contrato da Bahrd para tudo que não vira caso.

    200 e não 4xx mesmo quando o payload é recusado: quem dispara webhook trata
    erro HTTP como endpoint quebrado e reduz as entregas. Perder o canal é pior
    que perder um evento.
    """
    return ResultadoDoEvento(
        status.HTTP_200_OK, {"atendido": False, "motivo": motivo}
    )


async def processar_evento_link(
    cfg: Settings, payload: dict, origem: str = "link"
) -> ResultadoDoEvento:
    """Traduz, decide e atende. **A única implementação do caminho real.**

    Extraída de `entrada_link` em 03/09/2026, sem mudança de comportamento, para
    a tela de eventos de teste do painel poder chamar exatamente isto.

    ⚠️ **O motivo de existir é o que ela NÃO deixa acontecer.** Chamar `_atender`
    direto, que era o atalho óbvio, roda o atendimento inteiro mas pula cinco
    guardas: escopo do catálogo, telefone ausente, lista de destinos, dedup e o
    `_registrar_atendido`. O teste da Central passaria por um caminho mais
    permissivo que o da Bahrd, e a tela mediria uma coisa diferente da que roda
    em produção. Um fluxo, dois porteiros: HMAC para a Bahrd, token para o painel.

    O que fica de fora, de propósito: assinatura e leitura do corpo. São a porta,
    e cada chamador tem a sua.

    `origem` marca de onde o caso veio, e nasce de **quem chamou**, nunca do
    corpo: pôr uma marca de confiança dentro de um payload assinado convidaria
    a falsificação da marca. Vale `link` para o webhook e `teste` para a tela
    do painel, que já provou identidade pelo token.
    """
    # ── 2. Tradução ─────────────────────────────────────────────────────────
    try:
        evento = parse_evento_webhook(payload)
    except PayloadInvalido as erro:
        # 422 e não 500: o problema é o conteúdo, e a Bahrd precisa saber disso
        # para corrigir na origem em vez de reenviar o mesmo payload.
        log.warning("eventos_link_payload_invalido", erro=str(erro))
        return ResultadoDoEvento(
            status.HTTP_422_UNPROCESSABLE_CONTENT, {"erro": str(erro)}
        )

    log.info(
        "evento_link_recebido",
        evento_id=evento.evento_externo_id,
        tipo=evento.codigo_evento or evento.rotulo_link,
        veiculo=evento.veiculo,
        em_escopo=evento.em_escopo,
    )

    # ── 3. Fora do catálogo nunca vira atendimento automático ───────────────
    if not evento.em_escopo:
        log.warning("evento_link_fora_de_escopo", rotulo=evento.rotulo_link)
        return _recusa("fora_do_catalogo")

    if not evento.telefone_contato:
        log.warning("evento_link_sem_contato", veiculo=evento.veiculo)
        return _recusa("sem_telefone")

    # ── 3b. Fora de produção, só escreve para quem foi autorizado ───────────
    #
    # A rota é pública pelo túnel. Sem esta lista, quem descobrisse a URL faria
    # a IA mandar mensagem, pelo número oficial da Bahrd, para qualquer celular
    # do Brasil.
    #
    # ⚠️ **A condição mudou em 03/09/2026, e a anterior estava errada.** A lista
    # só valia quando não havia `bahrd_webhook_hmac_secret`, pelo raciocínio de
    # que a assinatura já provava quem estava chamando. O raciocínio não se
    # sustenta enquanto o segredo é o literal `dev-hmac-nao-usar-em-producao`,
    # versionado no `.env.example` desde d62f5b1: qualquer pessoa com leitura do
    # repositório assina um POST válido e faz o número oficial da Bahrd escrever
    # para o celular que quiser. A configuração ficava **pior que a vazia**,
    # porque configurar o segredo desligava a única proteção que sobrava, e
    # desligava justamente quando alguém fazia a coisa certa.
    #
    # Agora quem decide é o ambiente, não a presença de um segredo. Em produção
    # a lista não existe, porque aí a IA precisa mesmo falar com o cliente. Fora
    # dela vale sempre, com assinatura ou sem, e lista vazia recusa tudo: em
    # teste, não escrever para ninguém é o erro barato.
    #
    # ⚠️ **A tela de teste não passa por aqui, desde 03/09/2026.** Esta lista
    # protege uma rota **pública**, cujo corpo vem de fora e cujo único porteiro
    # é a assinatura. A tela do painel é outra porta: quem chama já provou
    # identidade com o token, escolheu o número na mão e passou pela validação de
    # formato, pelo teto diário e pelo 404 fora de desenvolvimento. Aplicar a
    # lista lá obrigaria a chamar o dev para cadastrar cada celular novo, que é o
    # que a tela existe para evitar.
    if (
        origem == "link"
        and not cfg.em_producao
        and not numero_autorizado(evento.telefone_contato, cfg.numeros_de_teste)
    ):
        # As grafias vão para o log pelo mesmo motivo de `whatsapp.py`: ver lado
        # a lado o que chegou e o que a lista reconhece transforma meia hora de
        # investigação em cinco segundos de leitura. Só sai fora de produção,
        # que é a única situação em que este ramo roda.
        log.warning(
            "evento_link_destino_nao_autorizado",
            veiculo=evento.veiculo,
            grafias=sorted(variantes_do_numero(evento.telefone_contato)),
            autorizados=len(cfg.numeros_de_teste),
        )
        return _recusa("destino_nao_autorizado")

    # ── 3c. O mesmo evento de novo não vira uma segunda ocorrência ──────────
    if _ja_atendido(evento.evento_externo_id):
        log.info(
            "evento_link_duplicado",
            evento_id=evento.evento_externo_id,
            veiculo=evento.veiculo,
        )
        return _recusa("duplicado")

    # ── 4. Atender ──────────────────────────────────────────────────────────
    #
    # `_atender` devolve a sessão, e não mais um `bool`, desde 03/09/2026: a
    # tela de teste precisa do `ocorrencia_id` para o recibo apontar direto para
    # a conversa. Para a Bahrd nada muda, porque a resposta dela continua sendo
    # montada a partir de `atendido`.
    try:
        sessao = await _atender(cfg, evento, origem)
    except Exception as erro:  # noqa: BLE001 — 500 aqui faz a Bahrd parar de entregar
        log.exception("evento_link_erro_inesperado", erro=str(erro))
        return _recusa("erro_interno")

    atendido = sessao is not None

    # ⚠️ **Registra só o que deu certo, e essa ordem é a coisa toda.**
    #
    # Marcar antes de atender transformaria uma falha nossa em evento perdido:
    # a Bahrd reentrega justamente porque a primeira tentativa não completou, e
    # a reentrega encontraria a porta fechada por um atendimento que nunca
    # aconteceu. Registrar depois faz o certo nos dois casos: repetição de
    # sucesso é barrada, repetição de falha passa e tenta de novo.
    if atendido:
        _registrar_atendido(evento.evento_externo_id)

    return ResultadoDoEvento(
        status.HTTP_200_OK,
        {"atendido": atendido, "evento_id": evento.evento_externo_id},
        sessao=sessao,
    )


# ────────────────────────── idempotência do webhook ──────────────────────────
#
# ⚠️ **Defeito real, 01/09/2026.** O `_derivar_id` já existia, o docstring dele
# já se chamava "chave de idempotência", o `main.py` já dizia que a API
# "deduplica" — e **ninguém conferia nada**. A chave era calculada, escrita no
# log e jogada fora.
#
# O sintoma apareceu num teste de frota: o mesmo payload postado duas vezes,
# 42 s de diferença, abriu **duas ocorrências para a mesma placa** (AJL2532,
# evento `580b1f37…`). No painel viraram dois atendimentos idênticos, e no
# celular, duas notificações iguais.
#
# Em produção isso não depende de alguém repetir o teste: webhook é entrega
# **pelo menos uma vez**. Quem reentrega é a plataforma da Bahrd sempre que a
# primeira resposta demorar ou falhar, e cada reentrega abriria mais uma
# ocorrência e mandaria mais um template — cobrado.

#: Por quanto tempo um evento já atendido continua sendo reconhecido.
#:
#: A janela de reentrega da Bahrd não é conhecida (é a pergunta que está no doc
#: 22 para a TI deles). 6 h é folgado para retentativa de webhook e curto o
#: bastante para não segurar um alarme real do mesmo veículo no dia seguinte.
#:
#: ⚠️ O `_derivar_id` inclui o **momento** do evento, então dois alarmes de
#: verdade do mesmo caminhão dão chaves diferentes. O que esta janela barra é
#: a **repetição do mesmo evento**, não a repetição do mesmo veículo.
MEMORIA_DE_EVENTOS = timedelta(hours=6)

#: Evento já atendido → quando foi. Some no restart, como as sessões.
#:
#: Mesmo limite do `SESSOES`: vive no processo. Vai junto para o Redis quando as
#: sessões forem, e pelo mesmo motivo — ver doc 16.
_ATENDIDOS: dict[str, datetime] = {}


def _ja_atendido(evento_id: str) -> bool:
    """Este evento já virou ocorrência há pouco?

    Poda na leitura, como o `SESSOES.vivas()`: sem depósito externo não há como
    varrer por relógio, e a leitura é o único momento em que se sabe que a
    entrada envelheceu.
    """
    agora = datetime.now(UTC)
    for chave, quando in list(_ATENDIDOS.items()):
        if agora - quando > MEMORIA_DE_EVENTOS:
            del _ATENDIDOS[chave]
    return evento_id in _ATENDIDOS


def _registrar_atendido(evento_id: str) -> None:
    _ATENDIDOS[evento_id] = datetime.now(UTC)


def esquecer_eventos() -> None:
    """Zera a memória. Existe para os testes, que não podem herdar estado."""
    _ATENDIDOS.clear()


def _resposta(codigo: int, **corpo: object) -> Response:
    """JSON com charset explícito — sem ele, acento vira caractere quebrado."""
    return Response(
        content=json.dumps(corpo, ensure_ascii=False),
        status_code=codigo,
        media_type="application/json; charset=utf-8",
    )


async def _atender(cfg: Settings, evento, origem: str = "link") -> Sessao | None:
    """Abre a ocorrência e conduz — mesmo caminho do `_abrir` do WhatsApp.

    Devolve a sessão aberta, ou `None` quando o evento não virou atendimento.
    Devolvia `bool`; virou a sessão em 03/09/2026 porque o recibo da tela de
    teste precisa apontar para a ocorrência, e reabri-la por busca depois seria
    procurar o que a função já tinha na mão.

    A diferença é a origem dos dados: aqui vêm do payload da Bahrd, não da
    amostra. O identificador do veículo é a **placa**, porque o webhook não traz
    IMEI (doc 08 §3) — a fonte devolve ficha neutra para quem não conhece, que
    é honesto enquanto a leitura real não existir.
    """
    tipo = eventos.por_codigo(evento.codigo_evento or "")
    if tipo is None or tipo.playbook is None:
        log.warning("evento_link_sem_playbook", tipo=evento.codigo_evento)
        return None

    # ⛔ **Antes de qualquer coisa: este número pediu para sair desta placa?**
    #
    # A checagem vem aqui, e não na hora de postar na Meta, porque o custo de
    # errar não é só a mensagem. Abrir a ocorrencia gastaria turno de IA, criaria
    # caso no painel e — o que importa — mandaria template cobrado para quem
    # pediu para parar de receber. Parar de mandar depois do pedido é obrigação
    # de plataforma: ignorar derruba a nota de qualidade do número na Meta.
    #
    # ⚠️ O evento NÃO é descartado: ele segue existindo no sistema da Bahrd e o
    # alarme continua valendo para quem mais estiver no cadastro. O que não
    # acontece é o contato com ESTE número sobre ESTA placa.
    if evento.telefone_contato and await numeros_removidos.esta_removido(
        cfg, evento.telefone_contato, evento.veiculo
    ):
        log.info(
            "evento_para_numero_removido",
            tipo=evento.codigo_evento,
            veiculo=evento.veiculo,
        )
        return None

    fonte = construir_fonte(cfg)
    contexto = await fonte.contexto(evento.veiculo, evento.momento)

    # O payload vence a amostra: nome e posição vieram do evento real, e são
    # mais confiáveis que qualquer coisa que a fonte de exemplo devolva.
    dados = {
        "placa": evento.veiculo,
        "interlocutor": evento.motorista or contexto.ficha.motorista or "o motorista",
        "posição": (contexto.posicao.endereco or "") if contexto.posicao else "",
        # O guincho credenciado saiu daqui em 03/09/2026. Ver o porquê no
        # `_abrir` de `whatsapp.py`, que monta o mesmo dicionário.
    }

    sessao = SESSOES.abrir(
        evento.telefone_contato,
        tipo,
        "TEXTO",
        dados,
        com_operador=cfg.escalonamento_humano_ativo,
        origem=origem,
        modelo=cfg.modelo_em_uso,
    )

    # Coordenada do evento, não da última posição conhecida: é onde a coisa
    # aconteceu, e é isso que o operador precisa ver no mapa.
    if evento.latitude is not None and evento.longitude is not None:
        sessao.latitude = evento.latitude
        sessao.longitude = evento.longitude
        # ⚠️ **O evento vem primeiro, e até 03/09/2026 não vinha.** Esta linha
        # lia só `contexto.posicao`, ou seja, a fonte de rastreamento — a
        # amostra, hoje. O parser já extraía `endereco` do payload (aceitando
        # `logradouro`, `endereco_completo` e `address`), e esse valor era
        # descartado aqui.
        #
        # O resultado era o oposto do que o comentário acima promete: a
        # coordenada vinha do evento e o logradouro vinha de outro lugar,
        # podendo apontar para um ponto diferente na mesma ficha.
        sessao.endereco = evento.endereco or (
            contexto.posicao.endereco if contexto.posicao else None
        )

    if origem == "teste":
        # Primeira linha da trilha, antes de qualquer outra: a auditoria nunca
        # perde uma linha, e é por ela que alguém lendo o caso meses depois
        # descobre que aquilo foi um teste e não um caminhão.
        sessao.anotar(
            "TESTE",
            f"<b>Disparo de teste pela Central</b> — não veio do sistema da "
            f"Bahrd. Cérebro: {cfg.modelo_em_uso}.",
        )

    sessao.anotar(
        "SISTEMA",
        f"Evento recebido do sistema da Bahrd — <b>{tipo.rotulo}</b> · "
        f"veículo {evento.veiculo}."
        if origem != "teste"
        else f"<b>{tipo.rotulo}</b> · veículo {evento.veiculo}.",
    )
    log.info(
        "evento_link_ocorrencia_aberta",
        ocorrencia=sessao.ocorrencia_id,
        tipo=tipo.codigo,
        evento_id=evento.evento_externo_id,
    )

    # ── A triagem decide quem conduz. Ela não decide se o cliente é avisado ──
    #
    # ⚠️ **"Tem que chegar no número do cliente."** Leonardo, 02/09/2026, depois
    # de três pânicos de teste em que nada saiu.
    #
    # Até aqui a triagem barrava o contato inteiro: acima do limiar, nenhuma
    # mensagem. O raciocínio era o `PB-PANICO` — se o botão foi apertado de
    # verdade, escrever avisa quem estiver do lado do motorista.
    #
    # **O que derruba isso é o próprio template aprovado.** O `evento_panico`
    # foi escrito e aprovado na Meta para sair num acionamento, com botão de
    # ligação para o 0800. A Bahrd já decidiu que o cliente é notificado; barrar
    # o envio aqui era o código sendo mais restritivo que a política dela.
    #
    # ⚠️ **E o que a triagem continua decidindo é o mais importante.** Acima do
    # limiar ela não autoriza a IA a encerrar (`triagem_autoriza_encerrar` fica
    # falso), e o `_encaminhar` deixa o caso aberto esperando uma pessoa. O
    # cliente recebe a notificação e o 0800; quem julga o caso é gente.
    #
    # ⛔ O texto do template diz "Acionamento do botão de pânico", e a
    # `observacao` do catálogo diz que a IA nunca abre a conversa dizendo
    # "pânico". **As duas coisas se contradizem, e a contradição é da Bahrd, não
    # nossa** — o template é o artefato aprovado por eles. Vale levantar.
    autorizada = True
    if tipo.exige_triagem_previa:
        autorizada = await _triar(cfg, sessao, contexto)

    sessao.anotar(
        "POLITICA",
        f"Liberado para contato — playbook <b>{tipo.playbook}</b>, canal WhatsApp."
        if autorizada
        else f"Notificação enviada, <b>condução com uma pessoa</b> — {tipo.playbook}.",
    )

    # ── Todo evento abre com template. Sempre. ──────────────────────────────
    #
    # ⚠️ **Havia um desvio aqui, e ele custava caro na coisa errada.** Quando a
    # janela de 24 h já estava aberta, a abertura saía como texto livre da IA,
    # para não pagar um template que "sairia grátis de outro jeito".
    #
    # Duas coisas derrubaram esse raciocínio, as duas em 01/09/2026:
    #
    # 1. **Template dentro da janela aberta não é cobrado.** Não é teoria: a
    #    fatura de agosto traz 158 templates `UTILITY` enviados dentro da
    #    janela, custo R$ 0,00. O desvio economizava zero.
    # 2. **E pagava por isso com a notificação.** O cliente de frota, cujos
    #    caminhões estão todos no mesmo telefone, recebia o primeiro evento
    #    completo — mapa, placa, logradouro, botões — e todos os seguintes como
    #    uma frase solta da IA. Justo o cliente que mais gera evento.
    #
    # Agora cada evento de cada veículo abre a sua própria notificação
    # completa, e o `_falar` volta a ser o que sempre foi: o que a IA diz
    # **depois** que a pessoa responde.
    #
    # ⚠️ **Menos quando a triagem fechou o caso.** `encerra_sem_operador` é
    # verdadeiro para tudo que não seja pânico, e ali o `_encaminhar` encerra:
    # mandar notificação de um caso já fechado seria escrever para alguém que
    # ninguém vai atender depois. Esta linha é o que mantém o raio da mudança
    # de 02/09 restrito ao pânico.
    if not sessao.viva:
        return None

    return sessao if await _abrir_com_template(cfg, sessao, evento) else None


async def _abrir_com_template(cfg: Settings, sessao, evento) -> bool:
    """Primeira mensagem por template, quando a janela está fechada.

    É o caso normal em produção: o motorista não falou com a central antes de o
    caminhão fazer alguma coisa.

    A IA **não escreve** este texto — ele foi aprovado pela Meta palavra por
    palavra, e mudar um caractere invalida a aprovação. O que a IA faz vem
    depois, quando a pessoa responder e a janela abrir.
    """
    # Já no formato que a Meta aceita, e não só na hora de postar: é com estes
    # valores que `modelos.corpo()` reconstrói o texto que o cliente leu, para
    # o histórico da IA e para o painel. Higienizar só no cliente HTTP faria as
    # duas versões divergirem, e a IA "lembraria" de uma mensagem diferente da
    # que saiu.
    tentativas = [
        (nome, [parametro_seguro(p) for p in parametros], localizacao)
        for nome, parametros, localizacao in templates_do_evento(sessao.tipo, evento)
    ]

    if not tentativas:
        log.warning("evento_link_sem_template", tipo=sessao.tipo.codigo)
        return False

    try:
        cliente = ClienteMeta(cfg)
    except MetaIndisponivel as erro:
        log.warning("meta_sem_credencial", erro=str(erro))
        return False

    resposta: dict | None = None
    modelo = ""
    #: Os parâmetros do modelo que **deu certo**, não do último tentado. É com
    #: eles que se reconstrói o texto que o cliente leu.
    enviados: list[str] = []
    usou_mapa = False

    try:
        for nome, parametros, localizacao in tentativas:
            try:
                resposta = await cliente.enviar_template(
                    sessao.telefone,
                    nome,
                    parametros=parametros,
                    localizacao=localizacao,
                )
            except MetaIndisponivel as erro:
                log.warning("template_falhou", template=nome, erro=str(erro))
                continue
            modelo = nome
            enviados = parametros
            usou_mapa = localizacao is not None
            break
    finally:
        await cliente.fechar()

    if resposta is None:
        return False

    # ⭐ **O que liga a resposta ao veículo certo.** Guardado antes de qualquer
    # outra coisa, porque um cliente com frota pode ter várias conversas vivas
    # neste mesmo telefone: quando ele tocar num botão, a Meta devolve
    # `context.id` apontando para esta notificação, e é assim que a rota sabe
    # de qual placa ele está falando. Ver `sessao_whatsapp.por_abertura()`.
    anotar_mensagem_enviada(sessao, ((resposta.get("messages") or [{}])[0]).get("id"))

    # ── Isto já está no celular da pessoa. Os dois lados precisam saber ─────
    #
    # Antes, o envio ficava só em `sessao.anotar()`, que é trilha de auditoria:
    # o modelo não lia e o painel não mostrava. Do ponto de vista do modelo não
    # havia assistente nenhum antes de si — e quem nunca falou se apresenta.
    # Foi assim que, em 25/08/2026, um "Olá vou ver aqui" recebeu de volta uma
    # apresentação e o recontar do evento que o cliente acabara de ler. Para o
    # operador, a conversa começava pela resposta do cliente a uma mensagem
    # invisível.
    #
    # Vai só quando o envio deu certo, e é essencial que seja assim: template
    # que falhou não chegou, e aí a apresentação é o comportamento correto.
    para_o_modelo = modelos.como_turno(modelo, enviados, com_mapa=usou_mapa)
    para_o_operador = modelos.corpo(modelo, enviados)
    if para_o_modelo is not None and para_o_operador is not None:
        sessao.registrar_template(para_o_modelo, para_o_operador, modelos.botoes(modelo))

    sessao.anotar(
        "IA",
        f"Primeiro contato por template aprovado — <b>{modelo}</b>. "
        "A conversa segue quando a pessoa responder.",
    )
    # `wa_id` é o número como a **Meta** o conhece, e nem sempre é o que
    # mandamos: no Brasil ela normaliza o nono dígito por conta própria. Quando
    # uma mensagem "sai" e não chega, comparar `para` com `wa_id` costuma ser a
    # primeira pista. O `mensagem_id` amarra este envio ao aviso de entrega que
    # volta pelo webhook.
    # A notificação saiu. A partir daqui, quem não responde também é caso —
    # nos eventos em que o catálogo diz que o silêncio é informação.
    vigiar_silencio_apos_template(cfg, sessao)

    # E o trace desta requisição ganha a ocorrência que ela abriu. Sem isto o
    # atendimento nascia partido em dois: o disparo de um lado, sem nome nem
    # sessão, e a conversa do outro — e quem abrisse a sessão no Langfuse via a
    # conversa sem o começo dela.
    marcar_notificacao(
        sessao.tipo.codigo,
        Identificacao(
            ocorrencia=sessao.ocorrencia_id,
            telefone=sessao.telefone.replace("whatsapp:", ""),
            nome=sessao.dados.get("interlocutor"),
            placa=sessao.dados.get("placa"),
            origem=sessao.origem,
        ),
    )

    contatos = resposta.get("contacts") or [{}]
    mensagens = resposta.get("messages") or [{}]
    log.info(
        "abertura_por_template",
        ocorrencia=sessao.ocorrencia_id,
        template=modelo,
        com_mapa=usou_mapa,
        para=sessao.telefone,
        wa_id=contatos[0].get("wa_id"),
        mensagem_id=mensagens[0].get("id"),
    )
    return True
