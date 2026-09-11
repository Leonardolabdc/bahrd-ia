"""A Central dispara evento de teste sem depender do Postman e sem depender do dev.

    tela do painel → POST /painel/testes/evento → processar_evento_link → WhatsApp

Existe porque quem valida o atendimento é a Central, e até aqui validar exigia
montar JSON à mão, saber o formato de data aceito, acertar o rótulo do evento
caractere por caractere e perguntar ao Leonardo o que deu errado quando nada
acontecia. A tela tira as quatro coisas do caminho: o rótulo vem do catálogo, o
horário é sempre agora, o payload é montado aqui, e a resposta explica a recusa
em português.

⛔ **É a parte mais travada do sistema, e a razão é uma só:** aqui o destino de
uma mensagem é escolhido por uma pessoa. Em todo o resto ele nasce de um evento
de veículo. Um clique daqui faz o número oficial **verificado** da Bahrd mandar
template para um celular, e no pânico esse template diz "Acionamento do botão de
pânico" e traz botão de ligação para o 0800 real da Central. Mandar isso para
quem não pediu é alarme falso com a credibilidade da empresa.

O risco mais provável não é ataque, é **um dígito errado**. Havia uma lista
fechada de destinos por causa disso, e ela saiu em 03/09/2026 (ver a trava 2).
O que restou é validação de formato e a conferência de quem aperta o botão.

As quatro travas, e a ordem importa:

1. `testes_pelo_painel` — desligada por padrão, e produção vence a variável.
   Desligada a rota devolve **404**, não 403: 403 confirma que a rota existe, e
   com `APP_ENV=dev` o `/openapi.json` está público.
2. Formato do destino — celular brasileiro válido, conferido no servidor e não
   só na tela.

   ⚠️ **Havia uma lista fechada de destinos aqui, e ela saiu em 03/09/2026, por
   decisão do Leonardo:** a Central precisa testar com o celular de quem estiver
   na sala, e uma lista no `.env` obrigaria a chamar o dev para cada número
   novo, que é justamente o que esta tela existe para evitar.

   ⛔ O que se perdeu com isso, dito por escrito para ninguém redescobrir
   sozinho: quem tiver o token do painel pode fazer a IA escrever para qualquer
   celular do Brasil. A validação de formato pega o dígito faltando, que era o
   erro mais provável, mas **não pega o dígito trocado** — e um dígito trocado
   manda "Acionamento do botão de pânico", com ligação para o 0800 real, para a
   casa de um estranho. O que sobrou contra isso é o token, o teto diário e o
   404 fora de desenvolvimento.
3. Teto diário — rígido, e aqui o princípio do resto do sistema **se inverte**.
   O `SECURITY.md` diz "alerta, nunca teto", porque teto no caminho de
   atendimento vira cliente sem resposta. Teste bloqueado não custa a ninguém.
4. O corpo do evento é montado **aqui dentro**, a partir de um catálogo de três.
   A alternativa era a rota assinar o que o chamador mandasse, e isso é um
   oráculo de assinatura: quem tivesse o token do painel passaria a assinar
   qualquer payload, e o HMAC deixaria de significar "veio da Bahrd".
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal
from zoneinfo import ZoneInfo

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from central_ia.api.rotas.eventos import processar_evento_link
from central_ia.api.seguranca import exigir_token_do_painel
from central_ia.config import Settings, settings
from central_ia.domain import eventos
from central_ia.integrations.rastreamento.bahrd_webhook import LIMITE_NOME, _telefone

log = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/painel/testes",
    tags=["painel"],
    dependencies=[Depends(exigir_token_do_painel)],
)

FUSO_PAINEL = ZoneInfo("America/Sao_Paulo")

#: Os três que a Central testa. Fechado de propósito: é o que impede a tela de
#: virar um "mande qualquer coisa" com cara de ferramenta oficial.
#:
#: O rótulo que vai no payload sai de `eventos.por_codigo`, nunca escrito aqui.
#: O parser casa o `tipo_evento` por **igualdade exata** contra o rótulo, então
#: um acento a menos numa cópia manual devolveria `fora_do_catalogo` sem dizer
#: por quê.
CODIGOS_DE_TESTE: tuple[str, ...] = (
    "REMOCAO_BATERIA",
    "MOVIMENTO_SEM_IGNICAO",
    "PANICO",
)

TipoDeTeste = Literal["REMOCAO_BATERIA", "MOVIMENTO_SEM_IGNICAO", "PANICO"]

#: Quantos disparos por dia, somando todo mundo que tem o token.
#:
#: Cinquenta é ~10x o que uma sessão honesta usa (o gestor manda 3 a 5 num teste
#: de 20 min). No pior tipo, o pânico, o dano fica em uns R$ 4/dia.
#:
#: ⚠️ Mora em memória, como `_ATENDIDOS` e `_SIMULADAS`. O compose sobe com
#: `--reload`, então salvar um `.py` zera o contador. É proteção contra clique
#: repetido, não contra quem quer burlar: quem quer burlar tem o token e já
#: passou por travas maiores.
TETO_POR_DIA = 50

#: Onde o veículo de teste "está", quando o disparo não informa outro ponto.
#:
#: Curitiba, que é onde a Bahrd opera. O valor em si importa pouco; o que importa
#: é **haver um**, para o disparo exercitar o `evento_alerta_mapa` e o cartão de
#: mapa chegar no celular, como chega num evento real.
LATITUDE_PADRAO = -25.4504094
LONGITUDE_PADRAO = -49.256198

#: O `Local:` da notificação, quando o disparo não informa outro.
#:
#: ⚠️ **É dado fixo de teste, e some sozinho em produção.** A cascata de
#: `local_do_evento` usa `evento.endereco` primeiro, então basta o rastreador
#: mandar o logradouro para este valor nunca mais ser usado.
#:
#: Existe porque sem ele o `Local:` saía como **"veja o mapa acima"**: com o
#: cartão de mapa junto e sem endereço, o template aponta para o cartão em vez
#: de mostrar coordenada crua para um motorista. Faz sentido em produção, e num
#: teste esconde justamente o campo que se quer conferir.
#:
#: ⛔ **Tem que bater com a coordenada padrão, e não batia.** Nasceu em
#: 03/09/2026 dizendo "Av. Sete de Setembro · Centro" enquanto a coordenada
#: acima cai na Rua Comendador Roseira, no Prado Velho — outro bairro. Passou
#: porque o painel desenhava um mapa de mentira ao lado, e desenho serve para
#: qualquer endereço. Apareceu no primeiro minuto em que o mini-mapa passou a
#: mostrar cartografia de verdade, no dia seguinte, com o pino numa rua e o
#: texto em outra.
#:
#: O valor abaixo é a geocodificação reversa da coordenada padrão, conferida na
#: mesma data. Sem número de porta de propósito: a rua é o que interessa, e é
#: endereço de rua que o rastreador manda. **Se uma mudar, a outra muda junto** —
#: e agora o mini-mapa cobra: endereço apontando para um lugar e pino para
#: outro fica visível na tela.
ENDERECO_PADRAO = "Rua Comendador Roseira · Prado Velho, Curitiba - PR"

_disparos: list[datetime] = []


def _dia_em_brasilia(momento: datetime) -> str:
    return momento.astimezone(FUSO_PAINEL).strftime("%Y-%m-%d")


def _usados_hoje() -> int:
    hoje = _dia_em_brasilia(datetime.now(UTC))
    return sum(1 for d in _disparos if _dia_em_brasilia(d) == hoje)


def _exigir_tela_ligada(cfg: Settings) -> None:
    """404 e não 403. 403 confirmaria que a rota existe."""
    if not cfg.testes_pelo_painel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


def celular_brasileiro(bruto: str) -> str | None:
    """E.164 de um celular brasileiro, ou `None`. Mais rígido que `_telefone`.

    ⚠️ **`_telefone` sozinho não bastava aqui, e o teste é que mostrou.**
    Ele só limpa a pontuação, prefixa `55` quando falta e confere o comprimento.
    Um número estrangeiro digitado por engano passa: `+1 415 555 0100` vira
    `5514155550100`, que tem 13 dígitos e parece um celular do DDD 14.

    No webhook isso é aceitável, porque quem manda é a plataforma da Bahrd e o
    número já vem do cadastro. Aqui alguém **digita**, e o campo virou livre em
    03/09/2026: um número que "quase" é brasileiro é exatamente o que a tela
    precisa recusar.

    As duas regras que fecham o buraco: DDD entre 11 e 99, e nove dígitos
    começando em 9. Não mexo em `_telefone` de propósito, para não arriscar
    recusar payload real da Bahrd por causa de uma tela interna.

    ⛔ Continua sem pegar o dígito **trocado**: `41999998888` e `41999998889`
    passam os dois, e o segundo é a casa de um estranho. Contra isso só a
    conferência de quem aperta o botão.
    """
    e164 = _telefone(bruto)
    if e164 is None:
        return None

    ddd, assinante = e164[3:5], e164[5:]
    if not 11 <= int(ddd) <= 99:
        return None
    if len(assinante) == 9 and not assinante.startswith("9"):
        return None
    if len(assinante) == 8 and assinante[0] not in "6789":
        return None
    return e164


# ─────────────────────────────── o catálogo ───────────────────────────────


class EventoDisponivel(BaseModel):
    codigo: str
    rotulo: str = Field(description="Vai no `tipo_evento` do payload, exato.")
    descricao: str = Field(description="O que a IA faz com este evento.")
    exige_triagem_previa: bool
    encerra_sem_operador: bool


class CatalogoDeTeste(BaseModel):
    """Tudo que a tela precisa para nunca inventar rótulo de evento.

    Trazia também o `formato_de_data`, que saiu junto com o campo de data e hora
    em 03/09/2026: sem alguém digitando data, não há formato para ensinar.
    """

    ativo: bool
    ambiente: str
    eventos: list[EventoDisponivel]
    usados_hoje: int
    teto_por_dia: int
    modelo_atual: str


def _descrever(tipo: eventos.TipoEvento) -> str:
    """O que vai acontecer, e **em qual aba olhar depois**.

    A frase antiga parava em "a IA conduz e pode encerrar sozinha", que é
    verdade e é metade da história: o mesmo evento termina em duas abas
    diferentes conforme o que o cliente responder. Quem dispara e não sabe disso
    procura o caso onde ele não está, e conclui que o teste falhou.
    """
    if tipo.exige_triagem_previa:
        return (
            "Passa primeiro pela triagem, que classifica o risco. O cliente é "
            "avisado nos dois casos. Se houver sinal de perigo, a IA não encerra "
            "e o caso fica em «Atendimento humano»; se não houver, ela conduz a "
            "conversa e o caso aparece em «Atendimento por IA» até terminar."
        )
    if not tipo.encerra_sem_operador:
        return (
            "A IA conversa com o cliente, mas nunca fecha sozinha: mesmo que "
            "corra tudo bem, o caso termina em «Atendimento humano» esperando "
            "alguém olhar."
        )
    return (
        "A IA conduz a conversa e o caso fica em «Atendimento por IA» enquanto "
        "isso. O desfecho depende do que o cliente responder: se ele explicar a "
        "causa, a IA encerra sozinha e o caso vai para «Encerrados»; se pedir "
        "ajuda, não responder ou disser algo que sugira risco, ela passa para "
        "«Atendimento humano» e o caso fica aberto para alguém assumir."
    )


@router.get(
    "/catalogo",
    response_model=CatalogoDeTeste,
    summary="O que a tela de eventos de teste pode disparar",
)
async def obter_catalogo() -> CatalogoDeTeste:
    cfg = settings()
    _exigir_tela_ligada(cfg)

    disponiveis = []
    for codigo in CODIGOS_DE_TESTE:
        tipo = eventos.por_codigo(codigo)
        if tipo is None:  # pragma: no cover — só se alguém renomear o catálogo
            continue
        disponiveis.append(
            EventoDisponivel(
                codigo=tipo.codigo,
                rotulo=tipo.rotulo,
                descricao=_descrever(tipo),
                exige_triagem_previa=tipo.exige_triagem_previa,
                encerra_sem_operador=tipo.encerra_sem_operador,
            )
        )

    return CatalogoDeTeste(
        ativo=True,
        ambiente=cfg.app_env,
        eventos=disponiveis,
        usados_hoje=_usados_hoje(),
        teto_por_dia=TETO_POR_DIA,
        modelo_atual=cfg.modelo_em_uso,
    )


# ─────────────────────────────── o disparo ───────────────────────────────


class PedidoDeTeste(BaseModel):
    tipo: TipoDeTeste
    telefone: str = Field(
        description="Celular brasileiro com DDD. Aceita máscara, `+55` e `whatsapp:`."
    )
    nome: str = Field(default="", max_length=LIMITE_NOME)
    placa: str = Field(default="ABC1D23", max_length=32)
    latitude: float | None = None
    longitude: float | None = None
    endereco: str = Field(default="", max_length=200)


#: Cada `motivo` que o fluxo devolve, dito em português e com o que fazer.
#:
#: ⚠️ **É metade do valor desta tela.** Oito desfechos de `processar_evento_link`
#: só existiam no log, e do lado de fora "não aconteceu nada" era indistinguível
#: de "o WhatsApp está lento". Quem testa sem saber por que falhou volta a
#: perguntar ao dev, que é exatamente o que a tela existe para evitar.
MOTIVO_EM_PORTUGUES: dict[str, str] = {
    "fora_do_catalogo": (
        "O tipo de evento não está no catálogo. Se você não mexeu no código, "
        "isto é defeito nosso: a tela só oferece três, e os três estão lá."
    ),
    "sem_telefone": (
        "O telefone não virou um número válido. Precisa ser celular brasileiro "
        "com DDD, por exemplo 41999998888."
    ),
    "destino_nao_autorizado": (
        "Este número não está autorizado a receber evento neste ambiente. "
        "Acrescente-o em TWILIO_NUMEROS_DE_TESTE ou use um que já esteja lá."
    ),
    "duplicado": (
        "Mesmo veículo, mesmo tipo e mesmo horário nas últimas 6 horas. O "
        "sistema trata como reenvio do mesmo evento, não como evento novo. "
        "Mande de novo sem preencher a data, que ela usa o horário de agora."
    ),
    "erro_interno": (
        "Algo quebrou do nosso lado depois de aceitar o evento. O log do "
        "container tem a exceção, procure por evento_link_erro_inesperado."
    ),
    "sem_playbook": (
        "O evento está no catálogo mas não tem playbook, então a IA não teria "
        "o que dizer."
    ),
}


class ReciboDeTeste(BaseModel):
    """O que aconteceu, dito de um jeito que dispensa ler log.

    Fica na tela, não some como um aviso passageiro: quem disparou precisa
    conseguir voltar nele depois de olhar o celular.
    """

    aceito: bool
    resumo: str
    motivo: str | None = None
    evento_id: str | None = None
    ocorrencia_id: str | None = None
    disparado_em: str
    para: str
    #: Vazio quando ninguém preencheu. A tela omite a linha nesse caso, em vez
    #: de mostrar um rótulo sem valor ao lado.
    nome: str = ""
    #: A placa entra no histórico junto do nome porque numa bateria de testes é
    #: o par que distingue um disparo do outro: o telefone costuma ser o mesmo.
    placa: str = ""
    tipo: str
    rotulo: str
    modelo: str
    usados_hoje: int
    teto_por_dia: int
    payload: dict = Field(
        description=(
            "O JSON exato que a rota montou. Fica aqui para a Central aprender "
            "o formato sozinha e conseguir reproduzir no Postman se quiser."
        )
    )


@router.post(
    "/evento",
    response_model=ReciboDeTeste,
    summary="Dispara um evento de teste pelo caminho real",
    description=(
        "Monta o payload internamente e chama `processar_evento_link`, a mesma "
        "função que o webhook da Bahrd usa. Não é simulação: manda WhatsApp de "
        "verdade para o número escolhido."
    ),
)
async def disparar(pedido: PedidoDeTeste) -> ReciboDeTeste:
    cfg = settings()
    _exigir_tela_ligada(cfg)

    # ⚠️ Conferido **no servidor**, não só na tela. A validação do formulário é
    # conveniência para quem digita; quem chama a rota por fora não passa por
    # ela, e o número inválido só apareceria lá na frente como `sem_telefone`,
    # sem dizer o que estava errado.
    #
    # Pega o dígito faltando, que é o erro comum. Não pega o dígito **trocado**:
    # `41999998888` e `41999998889` são os dois válidos, e o segundo é a casa de
    # um estranho. Contra isso não há validação possível, só a conferência de
    # quem aperta o botão.
    if celular_brasileiro(pedido.telefone) is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "Número inválido. Precisa ser celular brasileiro com DDD, por "
                "exemplo 41999998888."
            ),
        )

    usados = _usados_hoje()
    if usados >= TETO_POR_DIA:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Teto de {TETO_POR_DIA} eventos de teste por dia atingido. "
                "Zera à meia-noite, no horário de Brasília."
            ),
        )

    tipo = eventos.por_codigo(pedido.tipo)
    if tipo is None:  # pragma: no cover — o Literal já barra
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)

    # O horário é sempre **agora**, e não há como informar outro.
    #
    # ⚠️ **O campo de data e hora saiu da tela em 03/09/2026**, a pedido do
    # Leonardo. Ele existia para reproduzir um evento com horário específico, e
    # em troca dava três formas de errar: formato fora do que o parser aceita
    # (`%Y-%m-%d %H:%M:%S`, sem fuso e sem milissegundo), fuso trocado, e data
    # no passado num evento que a tela apresenta como acontecendo agora. Quem
    # testa quer disparar e olhar o celular.
    momento = datetime.now(UTC).astimezone(FUSO_PAINEL).strftime("%Y-%m-%d %H:%M:%S")

    # ⚠️ `id` próprio por disparo, e é isto que faz "mandar de novo" funcionar.
    #
    # Sem ele o fluxo derivaria a chave de idempotência de
    # `sha256(veiculo|rotulo|momento)`, e dois disparos do mesmo veículo no mesmo
    # segundo viriam como `duplicado` por 6 horas. Quem estivesse testando leria
    # isso como defeito da IA.
    #
    # ⛔ Em troca, a dedup **nunca** dispara por esta rota, nem de propósito: o
    # `id` novo vence qualquer repetição de placa, tipo e horário. Quem precisar
    # exercitar a deduplicação tem de repetir o `id`, e isso só dá pelo webhook.
    # (Um comentário anterior aqui dizia que bastava repetir o `momento`. Estava
    # errado, e a correção é esta.)
    payload: dict[str, object] = {
        "id": f"teste-{uuid.uuid4().hex[:16]}",
        "rotulo": pedido.placa,
        "data_hora_evento": momento,
        "tipo_evento": tipo.rotulo,
        "contato_telefone": pedido.telefone,
    }
    if pedido.nome:
        payload["contato_nome"] = pedido.nome
    payload["endereco"] = pedido.endereco or ENDERECO_PADRAO
    # ⚠️ **Coordenada sempre, com padrão quando o pedido não traz.**
    #
    # Até 03/09/2026 a tela nunca mandava latitude e longitude, e o efeito
    # passou despercebido em cinco disparos: `localizacao_do_evento` devolvia
    # `None`, o `evento_alerta_mapa` nem era tentado, e o cliente recebia a
    # notificação **sem o cartão de mapa**. O log dizia `com_mapa=false` nos
    # cinco, sem nada parecendo errado.
    #
    # ⛔ O problema não era a falta do mapa, era a tela testar **o caminho
    # errado**. Em produção a Bahrd manda `Latitude/Longitude` sempre; é a coluna
    # `Endereço` que vem vazia (doc 14 §5). Sem coordenada, o teste exercitava a
    # reserva de texto, que é o caminho de exceção, e dava por bom um fluxo que
    # não é o que roda.
    latitude = pedido.latitude if pedido.latitude is not None else LATITUDE_PADRAO
    longitude = pedido.longitude if pedido.longitude is not None else LONGITUDE_PADRAO
    payload["latitude"] = latitude
    payload["longitude"] = longitude

    log.info(
        "painel_teste_disparado",
        tipo=tipo.codigo,
        placa=pedido.placa,
        modelo=cfg.modelo_em_uso,
        usados_hoje=usados + 1,
    )
    # `origem="teste"` nasce daqui, de quem provou identidade com o token do
    # painel, e não de uma marca dentro do payload. Marca no corpo assinado
    # seria falsificável, e o que ela protege é justamente a leitura do painel:
    # um pânico de teste não pode ter a mesma cara de um pânico de motorista na
    # fila de quem está de plantão.
    resultado = await processar_evento_link(cfg, payload, origem="teste")
    _disparos.append(datetime.now(UTC))

    motivo = resultado.motivo
    if resultado.atendido:
        resumo = "Notificação enviada. Olhe o celular e acompanhe pelo painel."
    else:
        resumo = MOTIVO_EM_PORTUGUES.get(
            motivo or "",
            "O evento não virou atendimento e o sistema não disse por quê. "
            "Isto é defeito nosso, vale avisar.",
        )

    evento_id = resultado.corpo.get("evento_id")
    return ReciboDeTeste(
        aceito=resultado.atendido,
        resumo=resumo,
        motivo=motivo,
        evento_id=evento_id if isinstance(evento_id, str) else None,
        ocorrencia_id=getattr(resultado.sessao, "ocorrencia_id", None),
        disparado_em=momento,
        para=pedido.telefone,
        nome=pedido.nome,
        placa=pedido.placa,
        tipo=tipo.codigo,
        rotulo=tipo.rotulo,
        modelo=cfg.modelo_em_uso,
        usados_hoje=_usados_hoje(),
        teto_por_dia=TETO_POR_DIA,
        payload=payload,
    )


# ─────────────────────── qual cérebro atende o cliente ───────────────────────


#: Os três modelos que a Central pode escolher, e o que dizer de cada um.
#:
#: A ordem é do mais barato para o mais caro, e é a ordem em que a tela mostra.
#: O intermediário entrou em 03/09/2026, a pedido do Leonardo, para haver um
#: passo entre "barato e reprovado" e "caro e confiável".
#:
#: ⛔ **Enum fechado, nunca texto livre.** `ClienteOpenRouter` joga o valor
#: direto no campo `model` do payload da OpenRouter: string livre daria acesso
#: ao catálogo inteiro deles, inclusive modelos de US$ 75 por milhão de tokens.
#:
#: ⚠️ **O custo inclui o template da Meta, e isso muda a conclusão.** A tabela
#: do doc 06 compara só a parte de IA e dá 26x entre os extremos. Um atendimento
#: real começa com um template `UTILITY` de R$ 0,035, que é o **mesmo preço nos
#: três** e não depende de modelo nenhum. Somado, R$ 0,13 contra R$ 0,04: cerca
#: de 3x, não 26x. Mostrar os 26x aqui seria vender uma economia que não existe.
#:
#: ⛔ **Os defeitos medidos do Flash Lite saíram da tela em 03/09/2026**, a
#: pedido do Leonardo, junto com o selo de "não aprovado para produção". Diziam
#: que ele tratou um possível roubo como rotina e que 9% das conversas morreram
#: mudas, uma delas depois de o cliente pedir para falar com uma pessoa
#: (docs/arquivo/26).
#:
#: O que restou avisando é o `ORIENTACAO_DE_ESCOLHA`, que manda trocar para o
#: Sonnet quando a IA estiver conduzindo mal ou parando de responder — sintomas
#: dos mesmos defeitos, ditos pelo lado de quem observa em vez do de quem mediu.
#: `aprovado_para_producao` continua no contrato como registro da decisão.
MODELOS_DISPONIVEIS: tuple[dict[str, str], ...] = (
    {
        "id": "google/gemini-2.5-flash-lite",
        "nome": "Gemini 2.5 Flash Lite",
        "custo": "R$ 0,04 por atendimento",
        "custo_detalhe": "R$ 0,035 do template Meta + R$ 0,004 da IA",
        "custo_comparativo": "o mais barato",
        "resumo": "Barato.",
        "aprovado_para_producao": "não",
    },
    {
        "id": "google/gemini-2.5-flash",
        "nome": "Gemini 2.5 Flash",
        # ⚠️ **Estimado, não medido.** Os outros dois vieram de rodadas reais
        # (54 e 55 conversas); este é derivado, e por dois caminhos que
        # convergem:
        #
        #   • pelo perfil de tokens medido (~20.230 de entrada e ~600 de saída
        #     por turno), com os preços do doc 06, o Flash custa 3,34x o Flash
        #     Lite. Os dois pagam entrada cheia, porque o adaptador só manda
        #     `cache_control` para o prefixo `anthropic/`;
        #   • pela projeção mensal do próprio doc 06, R$ 96 contra R$ 29, a
        #     razão dá 3,31x.
        #
        # Ancorado no MEDIDO do Flash Lite (R$ 0,004 da IA): 0,004 × 3,34 ≈
        # R$ 0,013. Ancorar no Sonnet daria R$ 0,041, e seria pior: aquela
        # medição carrega a escrita de cache da Anthropic, que não se aplica
        # aqui. Mesma família e mesmo tratamento de cache é a comparação honesta.
        #
        # ⚠️ **A faixa real é R$ 0,05 a R$ 0,08, e a incerteza tem nome.**
        # Confrontando a projeção do doc 06 com o que foi medido de verdade:
        #
        #   Sonnet 5     projetado R$ 0,0933   medido R$ 0,0935   erro 1,00x
        #   Flash Lite   projetado R$ 0,0129   medido R$ 0,0036   erro 3,61x
        #
        # A projeção acerta a Anthropic na vírgula e **superestima o Gemini em
        # 3,6x**, quase certamente por cache implícito do Google, que o nosso
        # adaptador não pede nem enxerga. Então:
        #
        #   • se o Flash ganhar o mesmo desconto do Lite  → R$ 0,05 (o que está aqui)
        #   • se não ganhar, valendo a projeção crua       → R$ 0,08
        #
        # Fica o cenário provável, porque é o que a única medição comparável
        # indica. ⛔ Não inflar para R$ 0,08 por precaução: o Sonnet custa
        # R$ 0,13, e a 60% dele o intermediário lê como "quase o mesmo preço, vou
        # no melhor" — o número pessimista jogaria fora o degrau que ele existe
        # para ser. Só medir resolve.
        "custo": "R$ 0,05 por atendimento",
        "custo_detalhe": "R$ 0,035 do template Meta + R$ 0,013 da IA (estimado)",
        "custo_comparativo": "intermediário",
        "resumo": "Meio-termo.",
        # ⛔ Nem "sim" nem "não": **não foi medido**. Dizer "sim" seria mentir,
        # dizer "não" seria condenar sem prova. O Flash Lite reprovou numa
        # rodada de 55 conversas; este modelo não passou por nenhuma, e o
        # defeito que reprovou o Lite (roubo tratado como rotina) não se prevê
        # por tabela de preço.
        "aprovado_para_producao": "não testado",
    },
    {
        "id": "anthropic/claude-sonnet-5",
        "nome": "Sonnet 5",
        "custo": "R$ 0,13 por atendimento",
        "custo_detalhe": "R$ 0,035 do template Meta + R$ 0,09 da IA",
        "custo_comparativo": "o mais caro",
        "resumo": "O mais confiável.",
        "aprovado_para_producao": "sim",
    },
)

#: ⛔ Precisa listar exatamente os `id` de `MODELOS_DISPONIVEIS`. Um `Literal`
#: desatualizado devolve 422 para um modelo que a tela oferece, e o sintoma é um
#: botão que não faz nada.
ModeloPermitido = Literal[
    "anthropic/claude-sonnet-5",
    "google/gemini-2.5-flash",
    "google/gemini-2.5-flash-lite",
]


class PedidoDeModelo(BaseModel):
    modelo: ModeloPermitido


#: Qual escolher, e quando mudar de ideia.
#:
#: ⚠️ **Fica no servidor, junto da lista, e não escrito na tela.** É política de
#: operação, não texto decorativo: muda quando a medição mudar, e precisa mudar
#: nos dois lugares ao mesmo tempo. Escrito no React, viraria um parágrafo que
#: ninguém revisa quando o modelo for reavaliado.
ORIENTACAO_DE_ESCOLHA = (
    "Comece sempre pelo mais barato. Se perceber a IA conduzindo mal as "
    "tratativas ou parando de responder, suba um degrau: primeiro o Gemini 2.5 "
    "Flash, e o Sonnet 5 só se o problema continuar."
)

#: A mesma regra em cinco palavras, para o rótulo do retrátil fechado.
#:
#: ⚠️ Mora ao lado da longa **de propósito**. As duas dizem a mesma política, e
#: no dia em que o modelo for reavaliado as duas mudam juntas. Separadas, uma
#: envelheceria sozinha e a tela passaria a dar dois conselhos diferentes
#: dependendo de o bloco estar aberto ou fechado.
ORIENTACAO_CURTA = "troque só se a IA responder mal"


class EstadoDoModelo(BaseModel):
    atual: str
    orientacao: str = ORIENTACAO_DE_ESCOLHA
    orientacao_curta: str = ORIENTACAO_CURTA
    disponiveis: list[dict[str, str]]


@router.get(
    "/modelo",
    response_model=EstadoDoModelo,
    summary="Qual cérebro atende, e quais existem",
)
async def obter_modelo() -> EstadoDoModelo:
    cfg = settings()
    _exigir_tela_ligada(cfg)
    return EstadoDoModelo(
        atual=cfg.modelo_em_uso, disponiveis=list(MODELOS_DISPONIVEIS)
    )


@router.post(
    "/modelo",
    response_model=EstadoDoModelo,
    summary="Troca o cérebro que atende o WhatsApp do cliente",
    description=(
        "Vale da **próxima conversa** em diante. Quem já está falando com a IA "
        "termina no modelo em que começou."
    ),
)
async def trocar_modelo(pedido: PedidoDeModelo) -> EstadoDoModelo:
    """Troca o padrão, e só o padrão.

    ⚠️ **Por que mexer no `Settings` é seguro AQUI e não seria em outro lugar.**
    `settings()` é `@lru_cache(maxsize=1)` e o objeto não é `frozen`, então
    atribuir um campo propaga para todo mundo na hora, inclusive para as
    corrotinas que dormem em `_vigiar_silencio` segurando o mesmo `cfg`.

    Isso seria um desastre se o modelo fosse lido a cada turno: uma conversa de
    cliente real trocaria de cérebro no meio, com a triagem decidida por um
    modelo e a condução por outro, sem nada registrando. O que torna a troca
    segura é `Sessao.modelo`, carimbado na abertura: quem já está em conversa
    não lê mais o `cfg`.

    ⛔ Não use `settings.cache_clear()` para isto. Ele constrói um `Settings`
    **novo**, e toda corrotina dormindo fica presa no objeto antigo para
    sempre: dois modelos vivos ao mesmo tempo, sem nada na tela dizendo. O
    `cache_clear` do `conftest.py` é legítimo porque entre testes não há nada
    dormindo, e não é precedente para runtime.

    Não persiste: o processo reiniciar volta ao `.env`, e com `--reload` salvar
    qualquer `.py` faz isso. É limitação conhecida, não descuido; persistir
    exigiria depósito externo, que a POC ainda não tem.
    """
    cfg = settings()
    _exigir_tela_ligada(cfg)

    anterior = cfg.modelo_em_uso
    if pedido.modelo.startswith("anthropic/") and cfg.llm_provider != "openrouter":
        cfg.anthropic_modelo_principal = pedido.modelo.removeprefix("anthropic/")
    else:
        # A troca implica o provedor: os dois modelos da lista são servidos pela
        # OpenRouter, e deixar `llm_provider` para trás faria a tela dizer uma
        # coisa e o atendimento fazer outra.
        cfg.llm_provider = "openrouter"
        cfg.openrouter_modelo = pedido.modelo

    log.warning(
        "painel_modelo_trocado",
        de=anterior,
        para=cfg.modelo_em_uso,
        vale_a_partir_de="proxima_conversa",
    )
    return EstadoDoModelo(
        atual=cfg.modelo_em_uso, disponiveis=list(MODELOS_DISPONIVEIS)
    )
