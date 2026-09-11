"""Webhook do WhatsApp via Twilio — a conversa real com um celular.

    celular → Twilio → POST /whatsapp/entrada → política → IA → Twilio → celular

Duas coisas que este módulo protege:

1. **Assinatura conferida antes de qualquer coisa.** Sem isso, quem descobrisse
   a URL poderia injetar mensagem como se fosse um cliente, e a IA responderia
   — no celular de uma pessoa real. A conferência é o `X-Twilio-Signature`, e
   ela acontece antes de ler o conteúdo.
2. **Lista de números autorizados a abrir evento.** Responder numa conversa em
   curso é uma coisa; *iniciar* um atendimento em nome da central é outra. Só
   número cadastrado em `TWILIO_NUMEROS_DE_TESTE` abre.

O Twilio espera resposta em TwiML. Devolvemos TwiML vazio de propósito: quem
manda a mensagem é o nosso adaptador, de forma assíncrona, e não a resposta do
webhook — assim o mesmo caminho serve para quando a resposta demorar mais que
o timeout do Twilio.
"""

from __future__ import annotations

import asyncio
import html
import json
import re
from collections import OrderedDict
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Request, Response, status

from central_ia.agent import (
    atendimento_real,
    blindagem,
    pedido_de_humano,
    prompts,
    triagem_panico,
)
from central_ia.agent.escrita import sem_html, sem_saudacao_no_inicio, sem_travessao
from central_ia.api.rotas import midia
from central_ia.config import Settings, settings
from central_ia.domain import eventos
from central_ia.domain.eventos import LIMIAR_ENCERRAMENTO_AUTONOMO, LIMIAR_ESCALONAMENTO
from central_ia.integrations import voz
from central_ia.integrations.llm import construir_cliente_llm
from central_ia.integrations.mensageria import (
    ClienteTwilio,
    TwilioIndisponivel,
    assinatura_valida,
    numero_autorizado,
    variantes_do_numero,
)
from central_ia.integrations.mensageria.meta import (
    LIMITE_BOTOES,
    ClienteMeta,
    MetaIndisponivel,
    StatusDeEntrega,
    desafio,
    extrair_status,
)
from central_ia.integrations.mensageria.meta import (
    assinatura_valida as assinatura_meta_valida,
)
from central_ia.integrations.mensageria.meta import (
    extrair as extrair_meta,
)
from central_ia.integrations.rastreamento import construir_fonte
from central_ia.observability.logging import logger
from central_ia.observability.tracing import (
    Identificacao,
    marcar_sem_atendimento,
    span_da_triagem,
)
from central_ia.orchestration import numeros_removidos, tratativas
from central_ia.orchestration.sessao_whatsapp import (
    MAX_TURNOS_IA,
    SESSOES,
    Sessao,
    _chave,
)
from central_ia.ports.llm import Mensagem

log = logger(__name__)

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])

#: TwiML vazio. O Twilio exige XML válido; a mensagem sai por outro caminho.
TWIML_VAZIO = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'

#: Palavra que o celular manda para abrir um evento, e o código correspondente.
#: Curtas de propósito: quem está testando digita isso com o polegar.
#:
#: Três eventos, por decisão de demonstração — os que o gestor reconhece sem
#: explicação prévia. Velocidade saiu daqui, mas continua no catálogo e no
#: pipeline: é só devolver a linha quando fizer sentido mostrar.
GATILHOS: dict[str, str] = {
    "bateria": "REMOCAO_BATERIA",
    "ignicao": "MOVIMENTO_SEM_IGNICAO",
    "ignição": "MOVIMENTO_SEM_IGNICAO",
    "panico": "PANICO",
    "pânico": "PANICO",
}

#: Por quanto tempo uma resposta ainda "pertence" ao atendimento que fechou.
#: Vinte minutos cobre quem estava dirigindo e só parou depois para responder.
JANELA_DEPOIS_DO_FECHAMENTO = timedelta(minutes=20)

#: O que dizer para quem responde depois do encerramento.
#:
#: Não repete o desfecho nem promete retorno: o caso está fechado e a IA não
#: sabe se alguém vai olhar. Reconhece a mensagem, diz o que aconteceu, e deixa
#: claro que há um caminho — sem inventar qual.
DEPOIS_DO_FECHAMENTO = (
    "Obrigada, {nome}! Esse atendimento já foi encerrado e registrado aqui no "
    "sistema. Se precisar de mais alguma coisa, é só chamar a central."
)

#: O que dizer a quem escreve de um número que não abre ocorrência.
#:
#: **Nunca o motivo interno.** A versão anterior respondia *"Este número não
#: está autorizado a abrir ocorrência nesta POC. Peça para incluírem ele em
#: TWILIO_NUMEROS_DE_TESTE"* — nome de variável de ambiente na tela de um
#: motorista. Em 25/08/2026 isso chegou a um cliente logo depois de ele mandar
#: a palavra-chave de segurança, porque um restart tinha apagado a sessão da
#: memória e a mensagem caiu neste ramo.
#:
#: A frase não acusa o número nem nega atendimento: diz que não há conversa
#: aberta e aponta um caminho que funciona sempre, que é o 0800 da Central.
#: Quem precisa do motivo de verdade é quem lê o log, e lá ele está inteiro.
SEM_ATENDIMENTO_ABERTO = (
    "Oi! Aqui é a Central da Bahrd Monitoramento. Não localizei um "
    "atendimento aberto para este número. Se precisar falar com a gente "
    "agora, é só ligar 0800-080-8888."
)

AJUDA = (
    "Central IA — teste da POC.\n\n"
    "Mande uma destas palavras para abrir uma ocorrência e eu começo o "
    "atendimento:\n"
    "• bateria\n"
    "• ignicao\n"
    "• panico\n\n"
    "Depois é só responder como se você fosse o motorista."
)


#: Pontuação que o Deepgram acrescenta e que não faz parte da palavra.
_PONTUACAO = ".,!?;:…\"'“”‘’-–—"


#: Os dois botões do modelo de alerta, como estão publicados na Meta.
#:
#: Escritos aqui porque o código decide caminho a partir deles. Há teste
#: comparando com `modelos.botoes()` — renomear o botão no `.json` sem trocar
#: aqui faria o toque virar mensagem comum e o caminho fixo sumir em silêncio.
BOTAO_AJUDA = "Preciso de ajuda!"
BOTAO_TUDO_BEM = "Está tudo bem!"

#: O que o modelo lê junto do toque, e que o cliente nunca vê.
#:
#: **Existiu uma frase fixa aqui, e ela foi removida em 27/08/2026.** O roteiro
#: dos gestores mandava responder "vou lhe transferir para um colega
#: especialista" antes do turno da IA. Funcionou tecnicamente e falhou no que
#: importa: o modelo leu aquilo escrito em nome dele, concluiu — com toda a
#: razão — que o caso tinha saído das suas mãos, e o turno seguinte foi
#: *"Ok, Geraldo, vou registrar aqui no sistema. Qualquer dúvida é só entrar
#: em contato!"*. Encerrou em vez de tratar, no caso do cliente pedindo ajuda.
#:
#: Nenhuma nota conserta um histórico que diz o contrário dela. A correção foi
#: tirar a contradição, não explicá-la.
#:
#: ⛔ **Duas instruções saíram daqui em 10/09/2026, e as duas eram obedecidas.**
#: Esta nota mandava *"cumprimente com «{saudacao}» e o primeiro nome dele"* e
#: *"diga qual foi o evento em poucas palavras"*. Numa conversa real daquele
#: dia, o cliente tocou «Preciso de ajuda!» num pânico e a IA respondeu
#: *"Bom dia, Geraldo. Sobre o alerta de pânico do veículo ABC1D23…"*.
#:
#: Não foi o modelo desobedecendo — foi ele obedecendo. As duas instruções
#: nasceram quando o template era o antigo, que abria com «🚨Notificação de
#: Evento🚨» e não dizia nome nem saudação. O template de hoje abre com
#: *"Olá, bom dia, Geraldo! Tudo bem?"* e já nomeia o evento, então:
#:
#: * **cumprimentar de novo denuncia** que a primeira mensagem era automática,
#:   que é o oposto do que a saudação no template foi buscar;
#: * **nomear o evento de novo é repetição** — o cliente acabou de ler — e, no
#:   pânico, é violação da regra que manda em todas as outras do `PB-PANICO`:
#:   *"Você nunca diz que houve um pânico."* Quem estiver junto do motorista
#:   passa a saber que a central percebeu.
#:
#: ⚠️ **A primeira tentativa citava a placa, e durou uma conversa.** A frase era
#: *"Estamos acompanhando o veículo ABC1D23: quer me contar o que houve…"* — e
#: o template do pânico abre com *"Estamos acompanhando a viagem do veículo
#: ABC1D23"*. As duas mensagens, uma embaixo da outra, começavam com as mesmas
#: quatro palavras. Leonardo, olhando a conversa real: *"fica ruim repetir"*.
#:
#: A frase que ficou não repete nada do template e não precisa da placa: quem
#: lê acabou de ver a placa na mensagem de cima, e a conversa já está presa a
#: uma ocorrência só. Serve os três eventos sem exceção.
#: ⛔ **A ordem das frases desta nota é funcional, não estética.** Visto numa
#: conversa real de 10/09/2026, e a regressão foi introduzida horas antes, aqui
#: mesmo: o cliente tocou «Preciso de ajuda!» e a IA respondeu *"Claro, Pedro!
#: Já estou passando o seu atendimento para um dos nossos operadores"*. Escalou
#: sem perguntar nada.
#:
#: Três causas, e todas de redação:
#:
#: 1. **a instrução principal estava enterrada.** A nota abria com três «NÃO» e
#:    só depois dizia o que fazer. A versão anterior abria com *"faça três
#:    coisas"*, imperativa, na primeira frase — e funcionava;
#: 2. **«o botão diz que ele quer ajuda» + «se ele aceitar o operador»** deixava
#:    o toque parecer o aceite. Hoje a primeira linha nega isso explicitamente;
#: 3. **proibia encerrar, não escalar.** São coisas diferentes, e foi por essa
#:    fresta que passou.
#:
#: A regra que sobra: **o que fazer vem antes do que não fazer, e o ramo do
#: turno seguinte fica visivelmente separado do turno atual.**
NOTA_DO_BOTAO_DE_AJUDA = (
    "[O cliente TOCOU no botão «Preciso de ajuda!» da notificação. "
    "⚠️ TOCAR NESSE BOTÃO NÃO É ACEITAR FALAR COM UM OPERADOR. É só o começo da "
    "conversa: ele ainda não escolheu nada, e você ainda não sabe o que houve. "
    "NESTE TURNO você faz UMA coisa: manda exatamente esta frase, e mais nada. "
    "«Estamos à disposição, quer me contar o que houve ou prefere que eu passe "
    "para um dos nossos operadores te atender agora?» "
    "NÃO escale neste turno. NÃO use a marca de escalonamento neste turno. "
    "NÃO encerre a ocorrência neste turno: ninguém apurou nada ainda. "
    "NÃO cumprimente, não repita o nome do evento e não comece com «Estamos "
    "acompanhando» — a notificação já disse tudo isso, e repetir denuncia que a "
    "primeira mensagem era automática. "
    "SÓ NA RESPOSTA SEGUINTE, e conforme o que ele disser: "
    "se ele contar o que houve, conduza a tratativa normalmente; "
    "se ele aceitar o operador, de qualquer forma que aceite, inclusive um "
    "«sim» solto, aí sim use a marca de escalonamento, com a frase "
    "«Ok, {primeiro_nome}, vou passar para um operador te atender agora. "
    "Qualquer dúvida é só entrar em contato!» — e não a despedida de "
    "escalonamento que veio no contexto, que diz que você vai registrar no "
    "sistema. Aqui não é isso: o caso vai mesmo para a fila de uma pessoa, e o "
    "cliente precisa saber que alguém vai retomar. "
    "NUNCA diga que alguém vai ligar. Não controlamos isso: quem pegar o caso "
    "pode ligar ou escrever, e prometer o telefone deixa a pessoa esperando "
    "uma chamada que talvez venha como mensagem. Também não prometa prazo.]"
)


#: A palavra que o rodapé do template ensina.
#:
#: ⛔ **É atalho determinístico, não a única porta.** Parar de mandar mensagem
#: para quem pediu é obrigação de plataforma — ignorar derruba a nota de
#: qualidade do número na Meta e, no limite, tira a conta do ar, e aí *nenhum*
#: cliente recebe nada. Uma detecção que dependa só de interpretação do modelo
#: pode falhar num dia ruim; esta não depende de modelo nenhum.
#:
#: Quem escrever "não é meu carro", "mandou pro número errado" ou "cancela esse
#: número" cai na leitura da IA e chega no mesmo lugar — ver o `PB-COMUM`.
PALAVRA_DE_REMOCAO = "REMOVER"


def _pediu_remocao(corpo: str) -> bool:
    """A mensagem é só a palavra-chave?

    ⚠️ **Mensagem inteira, e não "contém".** «Não vou remover a bateria agora» é
    resposta ao evento, não pedido de descadastro — e tratar como pedido faria a
    IA perguntar se a pessoa quer parar de receber alarme do próprio caminhão no
    meio de um atendimento. Pontuação e acento são tolerados; o resto, não.
    """
    limpo = corpo.strip().strip(".!?,;:").casefold()
    return limpo == PALAVRA_DE_REMOCAO.casefold()


#: O que o modelo lê quando a palavra-chave chega, e o cliente nunca vê.
#:
#: ⛔ **A confirmação é enfática de propósito, e foi pedido explícito.** O que
#: está em jogo não é uma newsletter: quem confirma deixa de receber o alarme de
#: **roubo** daquele veículo naquele número. Um "ok, removido" silencioso faria
#: alguém descobrir o engano no dia em que o caminhão sumisse.
#:
#: A pergunta nomeia a placa e diz o que se perde, porque confirmação vaga é
#: confirmação que ninguém leu.
NOTA_DE_PEDIDO_DE_REMOCAO = (
    "[O cliente respondeu a palavra-chave do rodapé da notificação, que pede "
    "para parar de receber os avisos deste veículo. Ele NÃO digitou uma frase "
    "livre: tocou no atalho. "
    "NÃO remova nada ainda. Sua PRIMEIRA mensagem é só a confirmação, e ela "
    "precisa ser inequívoca — use exatamente esta frase: "
    "«{primeiro_nome}, antes de confirmar: TEM CERTEZA? Se eu remover, este "
    "número para de receber TODOS os avisos do veículo {placa}, inclusive "
    "alerta de roubo. Responda SIM para remover, ou qualquer outra coisa para "
    "continuar recebendo.» "
    "NÃO acrescente nada a essa mensagem, não cumprimente e não explique o "
    "evento. "
    "Se ele responder SIM, ou qualquer confirmação clara, agradeça em uma "
    "frase curta, diga que ele não receberá mais avisos deste veículo neste "
    "número, e encerre com a marca de desfecho "
    "«numero_removido_a_pedido». "
    "Se ele responder qualquer outra coisa, NÃO remova: diga que nada foi "
    "alterado e volte ao assunto do evento.]"
)


def _gatilho(corpo: str) -> str | None:
    """A primeira palavra da mensagem, se for um gatilho conhecido.

    A limpeza de pontuação não é firula: o `smart_format` do Deepgram pontua a
    transcrição, então um áudio dizendo "bateria" chega como `"Bateria."` — e
    a comparação crua falharia, devolvendo o menu para quem acabou de pedir o
    evento certo. Vale igual para quem digita com ponto final.
    """
    if not corpo.strip():
        return None
    primeira = corpo.split()[0].lower().strip(_PONTUACAO)
    return GATILHOS.get(primeira)


def _xml() -> Response:
    return Response(content=TWIML_VAZIO, media_type="application/xml")


def _url_recebida(request: Request, cfg: Settings) -> str:
    """A URL que o Twilio usou para assinar.

    Atrás de túnel (ngrok, cloudflared) o servidor enxerga `http://api:8000`,
    e o Twilio assinou `https://algo.ngrok.app`. Assinar sobre a URL errada
    invalida tudo — por isso a base pública é configuração, não dedução.
    """
    return cfg.public_base_url.rstrip("/") + request.url.path


async def _responder(
    cfg: Settings, para: str, texto: str, em_audio: bool = False
) -> str | None:
    """Entrega a resposta. Devolve o **endereço dela**, ou `None`. Nunca levanta.

    O retorno deixou de ser `bool` em 01/09/2026: um cliente de frota pode ter
    várias conversas vivas no mesmo telefone, e **citar uma mensagem nossa é
    como ele diz de qual caminhão está falando**. Sem guardar o `id`, só a
    notificação de abertura era endereçável, e toda fala da IA depois dela
    ficava fora de alcance.

    Truthiness preservada de propósito: quem só quer saber se entregou continua
    testando o valor, e nenhum chamador precisou mudar.

    Falha do TTS não vira silêncio: cai para texto. A pessoa recebendo a
    mensagem escrita é um atendimento pior; a pessoa não recebendo nada é um
    atendimento que não aconteceu.

    E falha do Twilio não vira erro HTTP. Deixar a exceção subir devolvia 500
    ao webhook, e isso custa duas coisas: o Twilio passa a tratar a nossa URL
    como quebrada e para de entregar; e a ocorrência, que já foi criada, fica
    pendurada sem ninguém saber. Quem chama decide o que fazer com o `False`.

    A limpeza fica aqui porque **este é o ponto único de saída dos dois
    canais**. Instrução de prompt é pedido; aqui é garantia.
    """
    texto = sem_html(sem_travessao(texto))
    if cfg.canal_whatsapp == "meta":
        return await _responder_meta(cfg, para, texto, em_audio)

    # O Twilio é sandbox de demonstração e não devolve um id que a Meta
    # reconheça, então aqui sai sempre o sentinela: entregou, mas não dá para
    # citar. Roteamento por citação é coisa do canal da Meta.
    #
    # ⚠️ **A construção fica dentro do try, e isso não é estilo.** Ela levanta
    # quando falta credencial, e estava fora: a função que promete "nunca
    # levanta" levantava. O caminho da Meta logo acima já se protegia disso; o
    # do Twilio não.
    #
    # Achado pelo CI em 02/09/2026, e o sintoma explica por que ninguém tinha
    # visto: na máquina de quem desenvolve o `.env` tem as credenciais, e a
    # exceção nunca acontecia. Onde ela acontece é onde ninguém está olhando —
    # dentro de um relógio de silêncio, numa tarefa `asyncio` que morre calada.
    try:
        twilio = ClienteTwilio(cfg)
    except TwilioIndisponivel as erro:
        log.warning("twilio_sem_credencial", erro=str(erro))
        return None

    try:
        if em_audio and cfg.whatsapp_responder_em_audio:
            try:
                audio = await voz.sintetizar(cfg, texto)
                nome = midia.guardar(audio, voz.TIPO_CONTEUDO)
                url = midia.url_publica(cfg.public_base_url, nome)
                await twilio.enviar_audio(para, url)
                return ENVIADO_SEM_ID
            except (voz.ElevenLabsIndisponivel, TwilioIndisponivel) as erro:
                log.warning("audio_falhou_caindo_para_texto", erro=str(erro))

        await twilio.enviar_texto(para, texto)
        return ENVIADO_SEM_ID
    except TwilioIndisponivel as erro:
        log.warning("whatsapp_entrega_falhou", para=para, erro=str(erro))
        return None
    finally:
        await twilio.fechar()


#: Devolvido quando a mensagem **saiu** mas não há id para citá-la depois.
#:
#: Verdadeiro como "entregou", inútil como endereço, e os dois usos precisam
#: dessa distinção: o Twilio não devolve um id que a Meta reconheça, e um
#: `True` seco esconderia isso de quem tenta rotear uma resposta citada.
ENVIADO_SEM_ID = "enviado"


async def _responder_meta(cfg: Settings, para: str, texto: str, em_audio: bool) -> str | None:
    """Mesmo contrato do caminho do Twilio: entrega, e **nunca levanta**.

    Devolve o `id` da mensagem na Meta, `ENVIADO_SEM_ID` quando saiu sem id, e
    `None` quando não saiu. Truthiness preservada: quem só quer saber se
    entregou continua testando o valor.

    Escrito à parte de propósito. O caminho do Twilio é o que foi demonstrado
    ao CEO — misturar os dois numa função só transformaria qualquer ajuste aqui
    em risco lá.
    """
    try:
        cliente = ClienteMeta(cfg)
    except MetaIndisponivel as erro:
        log.warning("meta_sem_credencial", erro=str(erro))
        return None

    try:
        if em_audio and cfg.whatsapp_responder_em_audio:
            try:
                audio = await voz.sintetizar(cfg, texto)
                nome = midia.guardar(audio, voz.TIPO_CONTEUDO)
                url = midia.url_publica(cfg.public_base_url, nome)
                return _id_da_resposta(await cliente.enviar_audio(para, url))
            except (voz.ElevenLabsIndisponivel, MetaIndisponivel) as erro:
                log.warning("audio_falhou_caindo_para_texto", erro=str(erro))

        return _id_da_resposta(await cliente.enviar_texto(para, texto))
    except MetaIndisponivel as erro:
        log.warning("whatsapp_entrega_falhou", para=para, erro=str(erro), canal="meta")
        return None
    finally:
        await cliente.fechar()


def _id_da_resposta(resposta: object) -> str:
    """O `id` que a Meta devolve, ou o sentinela quando ela não devolve.

    Defensivo porque o retorno é JSON de terceiro: um formato inesperado não
    pode derrubar uma mensagem que **já foi entregue**. Perder o endereço custa
    um roteamento por recência; levantar aqui custaria o atendimento.
    """
    try:
        return ((resposta or {}).get("messages") or [{}])[0].get("id") or ENVIADO_SEM_ID  # type: ignore[union-attr]
    except (AttributeError, IndexError, TypeError):
        return ENVIADO_SEM_ID


def _encaminhar(cfg: Settings, sessao: Sessao, motivo: str, explicacao: str) -> str:
    """Fim de linha do caso. Escala, ou encerra registrando o que teria escalado.

    Devolve a frase a dizer ao cliente.

    **O julgamento da IA não muda aqui.** Ela concluiu "isto é de um humano", e
    isso vai para a trilha do mesmo jeito nos dois modos. O que a chave
    `ESCALONAMENTO_HUMANO_ATIVO` decide é o destino — e ela existe porque nesta
    fase não há operador para receber, nem o dado interno da Bahrd para cruzar.

    Encerrar aqui **não** significa dizer que estava tudo bem: o desfecho
    gravado é o próprio motivo do escalonamento. Quem ler a lista de encerrados
    vê "reboque sem autorização do gestor", não "resolvido".
    """
    sessao.anotar("IA" if not cfg.escalonamento_humano_ativo else "SISTEMA", explicacao)

    frase = atendimento_real.despedida(
        sessao.dados.get("interlocutor"), cfg.escalonamento_humano_ativo
    )

    if cfg.escalonamento_humano_ativo:
        sessao.encerrar(motivo)
        sessao.escalada = True
        log.info("whatsapp_escalado", ocorrencia=sessao.ocorrencia_id, motivo=motivo)
        return frase

    # ── Nem todo evento pode ser encerrado por falta de operador ────────────
    #
    # ⚠️ **"Fechou sozinho, não pode acontecer isso."** Leonardo, 02/09/2026,
    # depois de um pânico que a triagem julgou provavelmente real sumir da tela.
    #
    # Para quase todo evento, encerrar aqui é razoável: o desfecho gravado é o
    # próprio motivo do escalonamento, e quem lê a lista de encerrados vê
    # "reboque sem autorização do gestor", não "resolvido".
    #
    # **No pânico não é.** Encerrado, o caso sai de "precisa de você" e vai para
    # os encerrados, onde ninguém volta a olhar. A chave existe porque não há
    # operador de plantão — mas o painel **é** como uma pessoa recebe, e ficar
    # aberto ali não depende de plantão nenhum.
    if not sessao.tipo.encerra_sem_operador:
        sessao.escalada = True
        sessao.anotar(
            "SISTEMA",
            "<b>Aguardando uma pessoa</b> — este evento não pode ser encerrado "
            "sem alguém olhar. O caso fica aberto na fila.",
        )
        log.warning(
            "whatsapp_aguardando_pessoa",
            ocorrencia=sessao.ocorrencia_id,
            tipo=sessao.tipo.codigo,
            motivo=motivo,
        )
        return frase

    sessao.anotar(
        "SISTEMA",
        "<b>Sem operador nesta fase da POC</b> — a IA encerrou o caso registrando "
        "o motivo pelo qual ele teria ido para uma pessoa.",
    )
    sessao.encerrar("encerrada_pela_ia", desfecho=motivo)
    log.info("whatsapp_encerrada_sem_operador", ocorrencia=sessao.ocorrencia_id, motivo=motivo)
    return frase


async def _dizer(cfg: Settings, sessao: Sessao, texto: str) -> bool:
    """Fala **e registra**. Toda mensagem que sai numa conversa passa por aqui.

    A separação entre `_responder` (só entrega) e esta função existe porque as
    duas primeiras vezes que escrevi uma despedida usei a de baixo direto — a
    mensagem chegava no celular e não aparecia no painel. Quem confere um caso
    encerrado via a conversa terminando no ar, sem a frase de fechamento, e
    concluía que a IA tinha largado o cliente falando sozinho.
    """
    # Limpa antes de registrar, e não só na entrega: senão o painel guardaria
    # uma frase e o cliente receberia outra — e é a cópia do painel que vira
    # HTML na tela do operador.
    texto = com_a_referencia(sessao, sem_html(sem_travessao(texto)))
    sessao.registrar_ia(texto, 0.0, em_audio=sessao.canal == "AUDIO")
    enviada = await _responder(
        cfg, sessao.telefone, texto, em_audio=sessao.canal == "AUDIO"
    )
    # ⭐ Guarda o endereço desta fala, para quem citá-la cair nesta conversa e
    # não na mais recente. Ver `Sessao.nossas_mensagens`.
    anotar_mensagem_enviada(sessao, enviada)
    return bool(enviada)


#: Separa a placa do evento dentro do rótulo. Ponto médio, não hífen: hífen se
#: confunde com o da própria placa em cadastro antigo (`ABC-1234`).
_SEPARADOR_DO_ROTULO = " · "

#: Tudo que não é letra nem número, para comparar placa escrita à mão.
_SO_ALFANUMERICO = re.compile(r"[^A-Za-z0-9]+")

# ───────────────── quando não dá para saber, pergunta ─────────────────
#
# ⚠️ **Decisão do Leonardo em 01/09/2026, revendo a minha.** Eu tinha escolhido
# não perguntar e cair na conversa mais recente, para poupar um turno. O teste
# mostrou o custo real dessa economia: ele escreveu *"Fui eu"* respondendo ao
# AJJ4567, a frase caiu no AAA4569 por recência, e as duas conversas seguiram
# erradas — uma respondendo o que não foi perguntado, a outra encerrando por
# silêncio.
#
# **Errar de qual caminhão se está falando é pior que gastar um turno.** Aqui a
# IA pergunta, e a resposta com a placa reencaminha a frase original para a
# conversa certa.

#: Telefone → (o que a pessoa disse antes de a gente perguntar, quando).
#:
#: Guardar a frase é o que faz a pergunta custar **um** turno em vez de dois.
#: Sem isto, ela responderia "AJJ4567", a conversa receberia só a placa, e a
#: pessoa teria de repetir o que já tinha escrito.
_PENDENTES: dict[str, tuple[str, datetime]] = {}

#: Depois disso a frase guardada é velha demais para ser reencaminhada.
#:
#: Curto de propósito: quem responde a "de qual veículo?" responde na hora. Meia
#: hora depois, a frase original perdeu o contexto até para quem a escreveu.
VALIDADE_DA_PENDENCIA = timedelta(minutes=10)


#: Telefone → (ocorrência que a pessoa identificou, quando).
#:
#: ⚠️ **A diferença entre continuar um assunto e adivinhar um.** Perguntar "de
#: qual veículo?" a cada frase virou interrogatório: em 01/09/2026 a mesma
#: pergunta saiu duas vezes em 43 segundos, no meio de uma conversa que já
#: estava clara para os dois lados.
#:
#: Guardar o foco só quando ela **disse** de qual é — toque em botão, citação
#: ou placa escrita. Nunca por recência: aí seria o palpite de volta com outro
#: nome, e o palpite é o que fechou o caminhão errado mais cedo no mesmo dia.
_FOCO: dict[str, tuple[str, datetime]] = {}

#: Por quanto tempo o assunto continua sendo o mesmo sem ela repetir a placa.
#:
#: Cinco minutos cobre uma conversa inteira com folga; passado isso, perguntar
#: de novo é razoável, porque ela pode ter voltado para outro caminhão.
JANELA_DO_FOCO = timedelta(minutes=5)


def _nota_da_volta(placa: str) -> Mensagem:
    """Diz ao modelo para anunciar a volta antes de retomar o assunto.

    Nota de sistema e não fala do cliente: ele não disse nada, e pôr palavra na
    boca dele faria a IA responder a algo que não aconteceu.
    """
    return Mensagem(
        papel="user",
        conteudo=(
            f"[SISTEMA] O atendimento do outro veículo terminou e agora é a vez do "
            f"{placa}, que estava esperando. **Comece a sua próxima mensagem "
            f"avisando que está voltando ao {placa}**, com as suas palavras, e só "
            "então continue de onde esta conversa parou. Não cumprimente de novo."
        ),
    )


async def _puxar_o_proximo_veiculo(cfg: Settings, encerrada: Sessao) -> None:
    """Fechou um caminhão e sobrou outro no mesmo número? A IA puxa o próximo.

    ⭐ **Pedido do Leonardo em 01/09/2026, e é a melhor solução do dia.** Ele
    tinha dois eventos abertos, concluiu um, e o outro ficava lá esperando um
    relógio vencer. A conversa certa é a que qualquer atendente humano faria:
    *"e sobre o AJH4554?"* — e continuar de onde parou.

    Isso resolve a ambiguidade na raiz, e não com mais um mecanismo. **Duas
    conversas paralelas eram o problema inteiro:** o roteamento por palpite, a
    pergunta "de qual veículo?", o rótulo em toda mensagem, todos existem
    porque a pessoa tinha dois assuntos abertos ao mesmo tempo. Fechando um e
    puxando o outro, sobra um assunto de cada vez.

    O foco vai junto: a próxima frase dela cai aqui sem precisar dizer a placa.

    Quem escreve a ponte é o modelo, não este código — ele recebe uma nota de
    sistema dizendo o que aconteceu e conduz com as palavras dele. Escrever a
    frase aqui daria a mesma ponte para todo evento e todo playbook.
    """
    restantes = SESSOES.vivas(encerrada.telefone)
    if not restantes:
        return

    proxima = restantes[0]
    placa_anterior = encerrada.dados.get("placa") or "o outro veículo"
    placa = proxima.dados.get("placa") or "este veículo"

    proxima.anotar(
        "SISTEMA",
        f"O atendimento do <b>{placa_anterior}</b> encerrou e este ficou aberto "
        f"— a IA puxa a conversa do <b>{placa}</b> de onde parou.",
    )
    log.info(
        "whatsapp_puxando_proximo_veiculo",
        encerrada=encerrada.ocorrencia_id,
        proxima=proxima.ocorrencia_id,
        placa=placa,
    )

    # O foco muda junto: a próxima frase dela é sobre este caminhão, e ela não
    # precisa dizer a placa para isso.
    _fixar_foco(encerrada.telefone, proxima)
    cancelar_espera(proxima.ocorrencia_id)

    # ⭐ **A pessoa já tinha tocado no botão desta notificação.** Ficou guardado
    # enquanto a outra conversa estava em andamento; agora vale, e ela não
    # precisa tocar de novo. Sem isto, a ponte perguntaria algo que ela já
    # respondeu.
    toque = proxima.toque_adiado
    proxima.toque_adiado = None
    if toque:
        log.info(
            "whatsapp_toque_adiado_aplicado",
            ocorrencia=proxima.ocorrencia_id,
            toque=toque,
        )
        # ⚠️ **Anuncia a volta antes de perguntar qualquer coisa.** Sem isto os
        # botões apareciam do nada logo depois de o outro caminhão fechar, e
        # quem lê não entende que o assunto mudou. O rótulo `[placa · evento]`
        # ajuda, mas ninguém lê rótulo como quem lê uma frase.
        volta = f"Voltando ao {placa}:"

        if toque in NOTA_POR_CAUSA:
            proxima.historico.append(_nota_da_volta(placa))
            await _atender_causa(cfg, proxima, toque, toque)
        elif toque == BOTAO_AJUDA:
            proxima.historico.append(_nota_da_volta(placa))
            await _atender_pedido_de_ajuda(cfg, proxima, toque)
        else:
            # Aqui o texto é nosso, não do modelo: a frase entra direto.
            await _perguntar_a_causa(cfg, proxima, toque, abertura=volta)
        return

    # Nota de sistema, não fala inventada do cliente: ele não disse nada, e pôr
    # palavra na boca dele faria a IA responder a algo que não aconteceu.
    proxima.historico.append(
        Mensagem(
            papel="user",
            conteudo=(
                f"[SISTEMA] O atendimento do veículo {placa_anterior} acabou de ser "
                f"encerrado. Esta conversa, do veículo {placa}, continua aberta e "
                "ficou sem resposta. Retome-a agora: diga que falta resolver este "
                "outro veículo, cite a placa, e repita a última pergunta que você "
                "fez aqui, com outras palavras. Não cumprimente de novo."
            ),
        )
    )
    await _falar(cfg, proxima)


def _primeiro_nome(sessao: Sessao) -> str:
    """Só o primeiro nome. O cadastro traz "Antônio da Silva, Transportes X"."""
    return (sessao.dados.get("interlocutor") or "").split(",")[0].split(" ")[0]


def _fixar_foco(telefone: str, sessao: Sessao) -> None:
    """Ela disse de qual veículo é. Vale para as próximas frases."""
    _FOCO[_chave(telefone)] = (sessao.ocorrencia_id, datetime.now(UTC))


def _foco_atual(telefone: str) -> Sessao | None:
    """A conversa que ela identificou há pouco, se ainda está viva."""
    guardado = _FOCO.get(_chave(telefone))
    if guardado is None:
        return None
    ocorrencia_id, quando = guardado
    if datetime.now(UTC) - quando > JANELA_DO_FOCO:
        _FOCO.pop(_chave(telefone), None)
        return None
    return next(
        (s for s in SESSOES.vivas(telefone) if s.ocorrencia_id == ocorrencia_id), None
    )


def _guardar_pendente(telefone: str, corpo: str) -> None:
    _PENDENTES[_chave(telefone)] = (corpo, datetime.now(UTC))


def _retirar_pendente(telefone: str) -> str | None:
    """A frase guardada, e a remove. `None` quando não há ou quando envelheceu."""
    guardado = _PENDENTES.pop(_chave(telefone), None)
    if guardado is None:
        return None
    corpo, quando = guardado
    return corpo if datetime.now(UTC) - quando <= VALIDADE_DA_PENDENCIA else None


def _tem_pendente(telefone: str) -> bool:
    return _chave(telefone) in _PENDENTES


#: Prefixo do `id` dos botões de desambiguação. O resto é o `ocorrencia_id`.
#:
#: É o que transforma um toque em roteamento exato: o `id` é **nosso**, volta
#: inteiro no webhook, e aponta para uma ocorrência específica. Nada de ler
#: placa digitada, nada de adivinhar.
PREFIXO_BOTAO_VEICULO = "veiculo:"


async def _perguntar_de_qual_veiculo(
    cfg: Settings, telefone: str, corpo: str, vivas: list[Sessao]
) -> None:
    """Pergunta de qual veículo é a resposta, e guarda o que a pessoa disse.

    **Por botão, com a placa em cada um.** A pessoa toca em vez de digitar, e o
    toque volta com o `ocorrencia_id` dentro: some a leitura de placa escrita à
    mão e some o palpite. Uma pergunta, um toque, conversa certa.

    ⚠️ **Acima de três conversas vivas cai para texto**, porque é o teto de
    botões da Meta. Aí a resposta volta a depender do `por_placa_citada`.

    A pergunta não pertence a nenhuma das conversas — é sobre qual delas é. Vai
    para a trilha de **todas** as candidatas, senão o operador que abrir uma
    delas veria a pessoa respondendo algo que ninguém perguntou ali.
    """
    candidatas = [s for s in vivas if s.dados.get("placa")]
    if len(candidatas) < 2:
        return  # sem placa não há o que perguntar; quem chama cai na recência

    placas = [s.dados["placa"] for s in candidatas]
    nome = (candidatas[0].dados.get("interlocutor") or "").split(",")[0].split(" ")[0]
    lista = ", ".join(placas[:-1]) + f" ou {placas[-1]}"
    pergunta = f"{nome + ', e' if nome else 'E'}sse é do {lista}?"

    _guardar_pendente(telefone, corpo)
    log.info(
        "whatsapp_perguntando_de_qual_veiculo",
        vivas=[s.ocorrencia_id for s in candidatas],
        placas=placas,
    )
    for sessao in candidatas:
        sessao.anotar(
            "IA",
            f"Resposta sem dizer de qual veículo — a IA perguntou entre "
            f"<b>{lista}</b> antes de seguir.",
        )

    if len(candidatas) <= LIMITE_BOTOES:
        botoes = [
            (f"{PREFIXO_BOTAO_VEICULO}{s.ocorrencia_id}", s.dados["placa"])
            for s in candidatas
        ]
        try:
            cliente = ClienteMeta(cfg)
        except MetaIndisponivel:
            await _responder(cfg, telefone, pergunta)
            return
        try:
            await cliente.enviar_botoes(telefone, pergunta, botoes)
            return
        except MetaIndisponivel as erro:
            # Sem botão a pergunta continua valendo em texto: a resposta cai no
            # `por_placa_citada`, que lê placa escrita à mão.
            log.warning("botoes_do_veiculo_falharam", erro=str(erro))
        finally:
            await cliente.fechar()

    await _responder(cfg, telefone, pergunta)


def por_placa_citada(telefone: str, texto: str) -> Sessao | None:
    """A conversa cuja **placa a pessoa escreveu** na mensagem.

    ⚠️ **Defeito real, 01/09/2026, e custou um atendimento.** Com duas conversas
    vivas, texto digitado caía sempre na mais recente. O Leonardo respondia
    sobre o AKJ4548, tudo ia para o AIO7569, e a IA **encerrou o caso do
    caminhão errado** com a informação do outro. Ele chegou a escrever
    *"eu falei da placa akj4548"* e o sistema mandou isso para o AIO7569
    também, porque ninguém estava lendo a placa.

    Escrever a placa é o que uma pessoa faz naturalmente para se corrigir, e
    era o único jeito que ela tinha de mudar de assunto. Agora funciona.

    Comparação sem acento de formato: `akj4548`, `AKJ-4548` e `AKJ 4548` são a
    mesma coisa. Falso positivo é quase impossível porque só se comparam as
    placas das conversas **vivas deste número**, que são duas ou três.

    `None` quando nenhuma placa aparece, e também quando **duas conversas vivas
    têm a mesma placa**: aí citar a placa não desambigua nada, e chutar seria
    repetir o defeito com outra cara.
    """
    alvo = _SO_ALFANUMERICO.sub("", texto).upper()
    if not alvo:
        return None

    achadas = [
        sessao
        for sessao in SESSOES.vivas(telefone)
        if (placa := _SO_ALFANUMERICO.sub("", sessao.dados.get("placa") or "").upper())
        and placa in alvo
    ]
    return achadas[0] if len(achadas) == 1 else None


def com_a_referencia(sessao: Sessao, texto: str) -> str:
    """Prefixa **placa e tipo do evento** quando há mais de uma conversa viva.

    ⚠️ **O problema que isto resolve não é do sistema, é da tela do cliente.**
    Um gestor de frota tem todos os veículos no mesmo número, então duas
    conversas paralelas caem na **mesma thread do WhatsApp**, intercaladas. Ele
    lê "qual desses é o caso?" e não tem como saber de qual caminhão.

    Visto num teste real em 01/09/2026: a abertura dizia a placa, porque o
    template a traz, e a pergunta seguinte não dizia nada.

        [AJL2532 · Remoção de bateria] Que bom, Antônio! Qual é o caso?

    **O tipo do evento entra junto, e não é redundância.** A placa sozinha não
    desambigua o mesmo caminhão com dois eventos ao mesmo tempo — bateria e
    pânico no AJL2532 são duas conversas, duas decisões e dois desfechos
    diferentes. Decisão do Leonardo em 01/09/2026.

    **Condicional de propósito.** Com um veículo só, repetir isso em toda frase
    é burocracia: a pessoa acabou de ler placa e evento no template logo acima,
    e a persona pede conversa de gente, não sistema de chamado. A referência só
    é útil quando existe ambiguidade, e é exatamente aí que ela aparece — e
    some sozinha quando a outra conversa encerra.
    """
    placa = (sessao.dados.get("placa") or "").strip()
    if not placa or len(SESSOES.vivas(sessao.telefone)) < 2:
        return texto

    rotulo = f"[{placa}{_SEPARADOR_DO_ROTULO}{sessao.tipo.rotulo}]"
    # Idempotente, e a checagem é pela placa e não pelo rótulo inteiro: o
    # modelo lê as próprias falas no histórico e imita o formato que vê, às
    # vezes com o texto do evento levemente diferente. Sem esta guarda sairia
    # `[ABC1D23 · Remoção de bateria] [ABC1D23 · ...] ...`.
    if texto.startswith(f"[{placa}"):
        return texto
    return f"{rotulo} {texto}"


def anotar_mensagem_enviada(sessao: Sessao, enviada: str | None) -> None:
    """Registra o `id` de uma mensagem nossa, quando ele existe e serve.

    Fica separado porque **três caminhos mandam mensagem** e os três precisam
    disto: a fala da IA (`_dizer`), a pergunta com botões e o template de
    abertura. Esquecer um deles reabre o buraco em silêncio — a conversa
    continua funcionando, e só a retomada do outro caminhão erra o destino.
    """
    if enviada and enviada != ENVIADO_SEM_ID:
        sessao.nossas_mensagens.add(enviada)


async def _ouvir(cfg: Settings, parametros: dict[str, str]) -> voz.Transcricao | None:
    """Baixa e transcreve o áudio da mensagem, se houver um.

    `None` quer dizer "não veio áudio". Falha na transcrição levanta — o
    chamador trata, porque tratar como silêncio seria pior: silêncio numa
    conversa de central é informação, e uma falha técnica não é silêncio.
    """
    if cfg.canal_whatsapp == "meta":
        return await _ouvir_meta(cfg, parametros)

    if parametros.get("NumMedia", "0") == "0":
        return None

    tipo = parametros.get("MediaContentType0", "")
    url = parametros.get("MediaUrl0", "")
    if not url or not tipo.startswith("audio"):
        return None

    twilio = ClienteTwilio(cfg)
    try:
        audio, tipo_real = await twilio.baixar_midia(url)
    finally:
        await twilio.fechar()

    return await voz.transcrever(cfg, audio, tipo_real or tipo)


#: Chaves que a rota da Meta usa para passar a mídia adiante. Prefixo com `_`
#: para não colidir com nada que o Twilio mande.
CHAVE_MIDIA_ID = "_meta_midia_id"
CHAVE_MIDIA_TIPO = "_meta_midia_tipo"


async def _ouvir_meta(cfg: Settings, parametros: dict[str, str]) -> voz.Transcricao | None:
    """Mesma promessa do caminho do Twilio: `None` é "não veio áudio".

    A diferença é o download em dois tempos — a Meta manda um `id`, não uma
    URL, e as duas chamadas precisam do cabeçalho de autorização.
    """
    midia_id = parametros.get(CHAVE_MIDIA_ID)
    tipo = parametros.get(CHAVE_MIDIA_TIPO, "")
    if not midia_id or not tipo.startswith("audio"):
        return None

    cliente = ClienteMeta(cfg)
    try:
        audio, tipo_real = await cliente.baixar_midia(midia_id)
    finally:
        await cliente.fechar()

    return await voz.transcrever(cfg, audio, tipo_real or tipo)


@router.get(
    "/meta",
    summary="Aperto de mão do webhook da Meta",
    description=(
        "A Meta chama esta URL ao salvar o webhook, com `hub.challenge`. "
        "Devolve o desafio **em texto puro** — JSON faz ela recusar a URL."
    ),
)
async def meta_desafio(request: Request) -> Response:
    cfg = settings()
    if cfg.meta_verify_token is None:
        log.warning("meta_sem_verify_token")
        return Response(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

    challenge = desafio(
        dict(request.query_params), cfg.meta_verify_token.get_secret_value()
    )
    if challenge is None:
        log.warning("meta_desafio_recusado")
        return Response(status_code=status.HTTP_403_FORBIDDEN)

    log.info("meta_webhook_verificado")
    return Response(content=challenge, media_type="text/plain")


#: Quantos identificadores de mensagem guardar para reconhecer repetição.
#:
#: 500 cobre com folga qualquer rajada de reenvio: a Meta reenvia em segundos,
#: não em horas. Guardar mais seria vazamento de memória lento sem ganho.
LIMITE_DE_MENSAGENS_VISTAS = 500

#: As mensagens que já foram processadas, na ordem de chegada.
_VISTAS: OrderedDict[str, None] = OrderedDict()


async def _mostrar_digitando(cfg: Settings, mensagem_id: str | None) -> None:
    """Acende o "digitando…" enquanto o modelo pensa. Nunca atrapalha.

    A IA leva uns três segundos para responder, e três segundos de silêncio
    depois de tocar num botão parecem travamento — quem acha que travou toca de
    novo, que foi metade da duplicata de 27/08/2026.

    Não custa nada: o indicador pega carona na confirmação de leitura, e
    confirmação de leitura não é mensagem entregue.

    Toda falha é engolida de propósito. Sem indicador a conversa fica como era
    ontem; com uma exceção aqui, ela não acontece.
    """
    if not mensagem_id:
        return
    try:
        cliente = ClienteMeta(cfg)
    except MetaIndisponivel:
        return
    try:
        await cliente.mostrar_digitando(mensagem_id)
    finally:
        await cliente.fechar()


def _ja_processada(mensagem_id: str | None) -> bool:
    """Esta mensagem já passou por aqui? Registra e responde.

    **O webhook da Meta é "pelo menos uma vez", não "exatamente uma vez".**
    Ela reenvia tudo que não recebe `200` rápido — e nós só devolvemos `200`
    **depois** de a IA responder, o que leva uns três segundos porque tem uma
    chamada de modelo no meio. Resultado: a Meta desiste de esperar, manda de
    novo, e a mesma fala do cliente é atendida duas vezes.

    Aconteceu em 27/08/2026, no primeiro teste do botão de causa. O painel
    mostrou "Em manutenção" duas vezes seguidas do cliente e duas respostas da
    IA — cada uma custando um turno e uma chamada paga, e a segunda respondendo
    a uma pergunta que a primeira já tinha feito.

    Deduplicar por identificador é a correção certa: ele vem da Meta, é único
    por mensagem, e sobrevive ao reenvio justamente por ser o mesmo. Responder
    `200` antes de processar seria a outra saída, e é pior — perderia a
    mensagem em qualquer falha nossa, porque a Meta já teria sido dispensada.

    Sem identificador, deixa passar: melhor atender duas vezes do que não
    atender.
    """
    if not mensagem_id:
        return False
    if mensagem_id in _VISTAS:
        return True

    _VISTAS[mensagem_id] = None
    while len(_VISTAS) > LIMITE_DE_MENSAGENS_VISTAS:
        _VISTAS.popitem(last=False)
    return False


@router.post(
    "/meta",
    summary="Recebe mensagem de WhatsApp vinda da Meta (Cloud API)",
    description=(
        "Cadastre esta URL no painel do app em *WhatsApp → Configuration → "
        "Webhook*, e assine o campo `messages`. Ver `docs/17`."
    ),
)
async def meta_entrada(request: Request) -> Response:
    """Sempre 200 quando a assinatura confere — mesma razão do Twilio.

    A Meta trata erro HTTP como endpoint quebrado e reduz as entregas. Falha
    nossa depois da assinatura é problema nosso, e a saída é registrar.
    """
    cfg = settings()

    if cfg.meta_app_secret is None:
        log.warning("meta_sem_app_secret")
        return Response(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

    # ── Assinatura sobre o corpo BRUTO, antes de virar JSON ─────────────────
    bruto = await request.body()
    if not assinatura_meta_valida(
        cfg.meta_app_secret.get_secret_value(),
        bruto,
        request.headers.get("X-Hub-Signature-256", ""),
    ):
        log.warning("meta_assinatura_invalida")
        return Response(status_code=status.HTTP_403_FORBIDDEN)

    try:
        payload = json.loads(bruto or b"{}")
    except json.JSONDecodeError:
        log.warning("meta_payload_ilegivel")
        return Response(status_code=status.HTTP_200_OK)

    # ── Avisos de entrega ───────────────────────────────────────────────────
    # Antes de qualquer coisa, porque é o único lugar onde a Meta conta o que
    # aconteceu com o que **nós** mandamos. `200` no envio só diz que ela
    # aceitou; se o número não tem WhatsApp ou o template caiu, a notícia chega
    # aqui — e antes de 24/08 era descartada em silêncio.
    for st in extrair_status(payload):
        if st.falhou:
            log.warning(
                "meta_entrega_falhou",
                para=st.destinatario,
                codigo=st.codigo,
                titulo=st.titulo,
                detalhe=st.detalhe,
                mensagem_id=st.mensagem_id,
            )
            _registrar_falha_de_entrega(cfg, st)
        else:
            log.info("meta_entrega", para=st.destinatario, situacao=st.situacao)

    houve_conversa = False
    try:
        # A Meta manda em lote; tratar só a primeira perderia conversa.
        for recebida in extrair_meta(payload):
            # A Meta reenvia o que não confirmamos rápido, e não confirmamos
            # rápido: o `200` só volta depois de a IA responder. Sem esta
            # trava, a mesma fala do cliente vira dois atendimentos.
            if _ja_processada(recebida.mensagem_id):
                log.info(
                    "meta_mensagem_repetida",
                    de=recebida.de,
                    mensagem_id=recebida.mensagem_id,
                )
                continue

            # "Digitando…" antes de pensar, não depois. Fica aqui e não no
            # `_fluxo` porque o `_fluxo` é dos dois canais, e o Twilio não tem
            # isso — misturar transformaria um recurso da Meta em condicional
            # no caminho compartilhado.
            await _mostrar_digitando(cfg, recebida.mensagem_id)

            houve_conversa = True
            parametros = {
                CHAVE_MIDIA_ID: recebida.midia_id or "",
                CHAVE_MIDIA_TIPO: recebida.midia_tipo or "",
            }
            await _fluxo(
                cfg,
                recebida.de,
                recebida.texto,
                parametros,
                recebida.botao,
                recebida.botao_id,
                recebida.contexto_id,
            )
    except Exception as erro:  # noqa: BLE001 — 500 aqui derruba o canal
        log.exception("meta_erro_inesperado", erro=str(erro))

    # Este endereço recebe duas coisas: a mensagem do motorista e os avisos de
    # entrega da Meta. Um disparo produz três ou quatro avisos, e sem esta marca
    # cada um virava um trace no Langfuse — 57 dos últimos 100, medido em
    # 25/08/2026, todos vazios. O Jaeger continua recebendo todos.
    if not houve_conversa:
        marcar_sem_atendimento()

    return Response(status_code=status.HTTP_200_OK)


@router.post(
    "/entrada",
    summary="Recebe mensagem de WhatsApp vinda do Twilio",
    description=(
        "Cadastre esta URL no Twilio em *Messaging → Try it out → WhatsApp "
        "sandbox settings*, campo **When a message comes in**, método POST."
    ),
)
async def entrada(request: Request) -> Response:
    """Sempre responde 200 quando a assinatura confere.

    O Twilio trata erro HTTP como webhook quebrado e reduz ou suspende as
    entregas. Qualquer falha nossa depois da assinatura é problema nosso, e a
    saída é registrar e escalar — não devolver 500 e perder o canal inteiro.
    """
    try:
        return await _processar(request)
    except Exception as erro:  # noqa: BLE001 — 500 aqui derruba o canal
        log.exception("whatsapp_erro_inesperado", erro=str(erro))
        return _xml()


async def _processar(request: Request) -> Response:
    cfg = settings()

    formulario = await request.form()
    parametros = {chave: str(valor) for chave, valor in formulario.items()}

    # ── 1. Assinatura, antes de olhar o conteúdo ────────────────────────────
    if cfg.twilio_auth_token is None:
        log.warning("whatsapp_sem_token")
        return Response(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

    assinatura = request.headers.get("X-Twilio-Signature", "")
    if not assinatura_valida(
        cfg.twilio_auth_token.get_secret_value(),
        _url_recebida(request, cfg),
        parametros,
        assinatura,
    ):
        log.warning("whatsapp_assinatura_invalida", de=parametros.get("From"))
        return Response(status_code=status.HTTP_403_FORBIDDEN)

    de = parametros.get("From", "")
    corpo = (parametros.get("Body") or "").strip()
    if not de:
        return _xml()

    await _fluxo(cfg, de, corpo, parametros)
    return _xml()


async def _fluxo(
    cfg: Settings,
    de: str,
    corpo: str,
    parametros: dict[str, str],
    botao: str | None = None,
    botao_id: str | None = None,
    contexto_id: str | None = None,
) -> None:
    """O atendimento em si, do áudio ao encerramento — **igual nos dois canais**.

    Fica fora de `_processar` porque a diferença entre Twilio e Meta é toda
    antes daqui: como a mensagem chega, como se confere a assinatura, o que se
    devolve ao webhook. A partir do texto do cliente, o tratamento é o mesmo — e
    duplicar isto seria garantir que os dois canais divergissem com o tempo.
    """
    # ── 2. Veio áudio? Transcreve antes de qualquer decisão ─────────────────
    #
    # A IA decide a partir do texto, nunca do áudio. Se a transcrição não for
    # confiável, tratar o palpite como fala do cliente seria decidir em cima de
    # algo que ninguém disse.
    veio_em_audio = False
    try:
        ouvido = await _ouvir(cfg, parametros)
    except Exception as erro:  # noqa: BLE001 — falha de áudio nunca vira silêncio
        log.warning("whatsapp_audio_falhou", de=de, erro=str(erro))
        await _responder(
            cfg, de, "Não consegui ouvir o seu áudio. Pode me escrever, por favor?"
        )
        return

    if ouvido is not None:
        veio_em_audio = True
        if not ouvido.confiavel:
            log.info("whatsapp_transcricao_fraca", de=de, confianca=round(ouvido.confianca, 2))
            await _responder(
                cfg,
                de,
                "Não deu pra entender direito o áudio — deve ser o barulho aí. "
                "Pode repetir, ou me escrever?",
                em_audio=True,
            )
            return
        corpo = ouvido.texto

    # Teto de tamanho **antes de qualquer coisa**: o texto ainda vai virar
    # contexto de modelo, e nada limitava isso. Uma colagem de 200 KB seriam
    # ~50 mil tokens de entrada numa mensagem só — custo e janela do modelo,
    # os dois estourados por quem não paga a conta. Ver `agent/blindagem.py`.
    if len(corpo) > blindagem.LIMITE_ENTRADA:
        log.warning("whatsapp_entrada_truncada", de=de, tamanho=len(corpo))
        corpo = blindagem.truncar(corpo)

    # Toda entrada abre a janela de 24 h da Meta. Registrar aqui é o que deixa
    # responder de graça depois, em vez de pagar template a cada disparo.
    SESSOES.registrar_entrada(de)
    log.info("whatsapp_recebido", de=de, tamanho=len(corpo), audio=veio_em_audio)

    # ── 3. Conversa em andamento tem prioridade. Mas QUAL delas? ────────────
    #
    # ⚠️ **Um telefone pode ter várias conversas vivas.** O cliente de frota
    # cadastra todos os veículos no mesmo número, e cada evento abre a sua
    # ocorrência. Até 01/09/2026 isto era `SESSOES.ativa(de)` e o segundo
    # caminhão apagava o primeiro — ver `sessao_whatsapp.Sessoes`.
    #
    # Duas fontes, nesta ordem, porque a primeira é certeza e a segunda é
    # palpite:
    #
    #   `contexto_id`  a Meta diz em qual notificação ela tocou. Vem em todo
    #                  toque de botão, que é como o fluxo começa.
    #   placa citada   ela escreveu a placa na mensagem. É o que uma pessoa faz
    #                  para se corrigir, e sem isto não havia como mudar de
    #                  assunto — ver `por_placa_citada`.
    #   mais recente   nenhum dos dois. Não há como saber, e o último evento é
    #                  o que ela acabou de ler.
    pelo_contexto = SESSOES.por_nossa_mensagem(de, contexto_id)
    pela_placa = None if pelo_contexto else por_placa_citada(de, corpo)

    # ── Não sei de qual veículo. Pergunta, em vez de chutar ─────────────────
    #
    # ⚠️ **Decisão do Leonardo em 01/09/2026, revendo a minha.** Eu tinha
    # escolhido chutar na conversa mais recente para poupar um turno. O teste
    # cobrou: *"Fui eu"* foi dito para o AJJ4567, caiu no AAA4569 por recência,
    # e as duas conversas seguiram erradas — uma respondendo o que não foi
    # perguntado, a outra encerrando por silêncio.
    #
    # Só quando **não há botão**: toque em botão sempre traz contexto, e
    # perguntar ali seria burocracia em cima de uma escolha já inequívoca.
    #
    # E pergunta **uma vez só**: se a resposta seguinte também não disser a
    # placa, cai na recência, porque insistir viraria laço.
    # A pessoa tocou na placa: o `id` do botão é nosso e aponta para a
    # ocorrência exata. É o caminho que não erra.
    pelo_botao = None
    if botao_id and botao_id.startswith(PREFIXO_BOTAO_VEICULO):
        escolhido = botao_id[len(PREFIXO_BOTAO_VEICULO) :]
        pelo_botao = next(
            (s for s in SESSOES.vivas(de) if s.ocorrencia_id == escolhido), None
        )
        botao = botao_id = None  # a escolha do veículo não é escolha de causa

    # Ela já disse de qual veículo há pouco. Continuar o assunto não é
    # adivinhar: é o que ela mesma estabeleceu.
    explicito = pelo_contexto or pela_placa or pelo_botao
    pelo_foco = None if explicito else _foco_atual(de)

    vivas = SESSOES.vivas(de)
    if (
        explicito is None
        and pelo_foco is None
        and not botao
        and not _tem_pendente(de)
        and len(vivas) > 1
    ):
        await _perguntar_de_qual_veiculo(cfg, de, corpo, vivas)
        if _tem_pendente(de):
            return

    # Ela acabou de dizer de qual é. O que tinha escrito ANTES volta a valer, e
    # é isso que faz a pergunta custar um toque em vez de uma repetição.
    identificou = pela_placa or pelo_botao
    if identificou is not None and (guardado := _retirar_pendente(de)):
        log.info(
            "whatsapp_frase_reencaminhada",
            ocorrencia=identificou.ocorrencia_id,
            placa=identificou.dados.get("placa"),
        )
        corpo = guardado
    elif explicito is None and pelo_foco is None:
        _retirar_pendente(de)  # não disse de qual é: a frase guardada vence aqui

    sessao = explicito or pelo_foco or SESSOES.ativa(de)

    # Só o que ela **disse** fixa o foco. Recência nunca: seria o palpite de
    # volta com outro nome, e foi ele que fechou o caminhão errado hoje cedo.
    if explicito is not None:
        _fixar_foco(de, explicito)
    if sessao is not None:
        vivas = SESSOES.vivas(de)
        if len(vivas) > 1:
            # Só registra. A escolha já foi feita acima; isto existe para o
            # operador entender o caso depois, se ele sair torto. Sem esta
            # linha, "a resposta caiu na ocorrência errada" seria indepurável.
            log.info(
                "whatsapp_varias_ocorrencias_no_numero",
                escolhida=sessao.ocorrencia_id,
                por=(
                    "contexto"
                    if pelo_contexto
                    else "placa"
                    if pela_placa
                    else "botao"
                    if pelo_botao
                    else "foco"
                    if pelo_foco
                    else "recencia"
                ),
                vivas=[s.ocorrencia_id for s in vivas],
                placas=[s.dados.get("placa", "") for s in vivas],
            )
        # ── Uma conversa de cada vez ────────────────────────────────────────
        #
        # ⚠️ **A metade que faltava, e ela custou um atendimento em 01/09/2026.**
        # O cliente tocou nos botões dos dois caminhões, as duas conversas
        # ficaram esperando resposta ao mesmo tempo, e o "Fui eu" que ele
        # digitou caiu na errada. Ele escreveu *"eu disse que fui eu da primeira
        # mensagem da outra placa"* e a IA, sem entender, encerrou.
        #
        # Tocar no botão é dizer "vi este alarme", e isso não se perde: fica em
        # `toque_adiado` e o `_puxar_o_proximo_veiculo` reaproveita quando a vez
        # chegar. O que não pode é abrir uma segunda frente — **duas perguntas
        # abertas na mesma janela do WhatsApp é o que torna toda resposta
        # ambígua**, e todo o resto do roteamento vira remendo disso.
        em_andamento = next(
            (
                s
                for s in SESSOES.vivas(de)
                if s.ocorrencia_id != sessao.ocorrencia_id and s.houve_resposta
            ),
            None,
        )
        if botao and em_andamento is not None and not sessao.houve_resposta:
            na_fila = sessao.dados.get("placa") or "esse veículo"
            atual = em_andamento.dados.get("placa") or "o primeiro"
            nome = _primeiro_nome(em_andamento)

            # ⚠️ **O foco volta para quem está em andamento.** Ele foi fixado
            # lá em cima, quando o toque chegou por contexto — e um toque que
            # vai para a fila não pode levar o foco junto. Sem esta linha, a
            # frase seguinte dele caía na conversa enfileirada: em 01/09/2026
            # o BBD2336 entrou na fila e roubou a resposta que era do AJJ3663.
            _fixar_foco(de, em_andamento)

            sessao.toque_adiado = botao_id or botao
            sessao.registrar_toque_na_fila(botao)
            sessao.anotar(
                "CLIENTE",
                f"Tocou em <b>«{botao}»</b>, mas o atendimento do <b>{atual}</b> "
                "estava em andamento — esta conversa espera a vez.",
            )
            log.info(
                "whatsapp_conversa_na_fila",
                ocorrencia=sessao.ocorrencia_id,
                placa=na_fila,
                em_andamento=em_andamento.ocorrencia_id,
            )
            # ⚠️ **Vai na conversa de QUEM ELE TOCOU, não na que está em
            # andamento.** A primeira versão respondia na conversa ativa, e o
            # efeito era o oposto do pretendido: ele tocava no botão do AJJ3663
            # e recebia uma resposta marcada `[AKK7887]`. No painel, a
            # ocorrência do AJJ3663 ficava com o template e mais nada.
            #
            # A frase diz as duas placas de propósito: é ela que deixa claro
            # **qual das duas está sendo resolvida agora**.
            await _dizer(
                cfg,
                sessao,
                f"Anotei o alerta do {na_fila}{', ' + nome if nome else ''}. "
                f"Vamos terminar o {atual} primeiro e em seguida eu volto "
                "neste aqui.",
            )
            return

        # Toque em botão é escolha num menu que nós desenhamos, e por isso
        # pode disparar caminho fixo. A mesma frase **digitada** não pode: ela
        # é desabafo, e tratá-la como comando faria a IA responder um roteiro
        # a quem estava conversando.
        # ⚠️ **Um `elif` só, e não quatro `return`s.** É o que permite a linha
        # de baixo existir: seja qual for o caminho, se esta conversa terminou
        # aqui, a próxima do mesmo número precisa ser puxada.
        #
        # Visto em 02/09/2026: ele tocou nos dois botões, pediu atendente
        # humano no primeiro, e o segundo ficou esperando um relógio vencer. A
        # ponte estava ligada só no encerramento por desfecho, e escalonamento
        # não passa por lá.
        estava_viva = sessao.viva

        # ── O caso já é de uma pessoa. A IA para de falar ───────────────────
        #
        # ⚠️ **"A tratativa jogou para um humano no painel mas ficou
        # perguntando pro cliente."** Leonardo, 02/09/2026, e o defeito é da
        # correção da mesma tarde.
        #
        # Antes, `_encaminhar` encerrava a sessão, e sessão encerrada calava a
        # IA por consequência. Ao parar de encerrar o pânico — para o caso não
        # sumir da fila — a conversa ficou **viva**, e a IA voltou a responder
        # um caso que já tinha saído das mãos dela.
        #
        # ⭐ Os dois estados eram um só e precisavam ser dois: `encerrada` é o
        # caso acabou; `escalada` é a IA saiu. Agora `escalada` sozinha basta
        # para calar, e é o que permite o caso continuar aberto sem ela.
        #
        # A fala **entra na trilha** de qualquer jeito: quem for atender
        # precisa ler o que a pessoa disse enquanto esperava, e é justamente
        # num pânico que essa frase pode ser a mais importante do caso.
        if sessao.escalada and sessao.viva:
            sessao.registrar_cliente(corpo)
            sessao.anotar(
                "SISTEMA",
                "<b>A IA não respondeu</b> — o caso já está com uma pessoa.",
            )
            log.info(
                "whatsapp_calada_caso_e_de_pessoa",
                ocorrencia=sessao.ocorrencia_id,
                tipo=sessao.tipo.codigo,
            )
            return

        if botao_id in NOTA_POR_CAUSA:
            await _atender_causa(cfg, sessao, botao_id, botao or botao_id)
        elif botao == BOTAO_AJUDA:
            await _atender_pedido_de_ajuda(cfg, sessao, botao)
        elif botao == BOTAO_TUDO_BEM:
            await _perguntar_a_causa(cfg, sessao, botao)
        else:
            await _continuar(cfg, sessao, corpo, em_audio=veio_em_audio, ouvido=ouvido)

        # Fechou agora, por desfecho, por escalonamento ou por qualquer outro
        # motivo? Então é a vez do próximo veículo deste número.
        if estava_viva and not sessao.viva:
            await _puxar_o_proximo_veiculo(cfg, sessao)
        return

    # ── 4. Sem conversa: só número autorizado abre ocorrência ───────────────
    if not numero_autorizado(de, cfg.numeros_de_teste):
        # As grafias vão para o log porque foi exatamente isso que faltou em
        # 25/08: ver lado a lado o que chegou e o que a lista reconhece
        # transforma meia hora de investigação em cinco segundos de leitura.
        log.warning(
            "whatsapp_numero_nao_autorizado",
            de=de,
            grafias=sorted(variantes_do_numero(de)),
            autorizados=len(cfg.numeros_de_teste),
        )
        await _responder(cfg, de, SEM_ATENDIMENTO_ABERTO, em_audio=veio_em_audio)
        return

    codigo = _gatilho(corpo)
    if codigo is None:
        # A pessoa respondeu depois do encerramento? Então ela ainda está na
        # conversa que acabou de fechar — mandar o menu de teste da POC ali
        # expõe andaime interno e sugere que o atendimento anterior não
        # aconteceu. Aconteceu em 24/08/2026, no primeiro evento real.
        recente = SESSOES.encerrada_ha_pouco(de, JANELA_DEPOIS_DO_FECHAMENTO)
        if recente is not None:
            nome = (recente.dados.get("interlocutor") or "").split(",")[0].split(" ")[0]
            await _responder(
                cfg,
                de,
                DEPOIS_DO_FECHAMENTO.format(nome=nome or "então").replace(", então!", "!"),
                em_audio=recente.canal == "AUDIO",
            )
            return
        await _responder(cfg, de, AJUDA)
        return

    await _abrir(cfg, de, codigo, em_audio=veio_em_audio)
    return


#: Qual veículo da amostra cada gatilho usa. No webhook real o IMEI vem no
#: evento; aqui a escolha é o que faz a triagem ter um contexto plausível —
#: `panico` cai no veículo com histórico de acionamento acidental, que é o
#: cenário que dá para conversar.
IMEI_POR_EVENTO: dict[str, str] = {
    "PANICO": "XYZ4E56",
    "REMOCAO_BATERIA": "GHI7J89",
    "MOVIMENTO_SEM_IGNICAO": "GHI7J89",
    "VELOCIDADE_EXCEDIDA": "GHI7J89",
}


async def _abrir(cfg: Settings, de: str, codigo: str, em_audio: bool = False) -> None:
    """Roda a política, e só então (talvez) fala.

    O caminho é o mesmo do pipeline: evento crítico passa pela triagem **antes
    de qualquer contato**. A diferença é que aqui o contato é real, num celular
    — então a ordem importa ainda mais.
    """
    tipo = eventos.por_codigo(codigo)
    if tipo is None or tipo.playbook is None:
        await _responder(cfg, de, "Esse tipo de evento ainda não tem playbook nesta POC.")
        return

    fonte = construir_fonte(cfg)
    contexto = await fonte.contexto(IMEI_POR_EVENTO.get(codigo, "GHI7J89"), datetime.now(UTC))
    dados = {
        "placa": contexto.ficha.placa,
        "interlocutor": contexto.ficha.motorista or "o motorista",
        "posição": (contexto.posicao.endereco or "") if contexto.posicao else "",
        # ⛔ **O guincho credenciado saiu do contexto em 03/09/2026.**
        #
        # Ele ia para o modelo a cada turno para a IA **conferir** o nome que a
        # pessoa desse, sem dizê-lo primeiro: quem rouba um caminhão não sabe
        # qual guincho aquele cliente tem cadastrado, então nomear certo era
        # prova. Toda uma vigilância (`agent/vigilancia.py`) existia para
        # detectar a IA citando antes da hora.
        #
        # Caiu por baixo: **a Central não valida guincho na tratativa real.**
        # Leonardo, 03/09/2026. O dado do cadastro nunca foi conferido contra o
        # que acontece, então a "prova" provava contra uma referência que
        # ninguém mantém — e para isso ela pagava o preço de manter o nome do
        # guincho dentro do contexto do modelo a cada turno.
        #
        # A pergunta que ficou no lugar é a duração da supressão, e ela não
        # precisa de nada disso.
    }

    # Espelhar o canal: quem abriu por áudio está dirigindo e não vai parar
    # para ler. O canal fica na sessão porque vale para a conversa inteira.
    sessao = SESSOES.abrir(
        de,
        tipo,
        "AUDIO" if em_audio else "TEXTO",
        dados,
        com_operador=cfg.escalonamento_humano_ativo,
        modelo=cfg.modelo_em_uso,
    )
    if contexto.posicao is not None:
        sessao.latitude = contexto.posicao.latitude
        sessao.longitude = contexto.posicao.longitude
        sessao.endereco = contexto.posicao.endereco
    sessao.anotar(
        "SISTEMA",
        f"Evento recebido pelo WhatsApp — <b>{tipo.rotulo}</b> · "
        f"canal {'áudio' if em_audio else 'texto'}.",
    )
    log.info("whatsapp_ocorrencia_aberta", ocorrencia=sessao.ocorrencia_id, tipo=codigo)

    if tipo.exige_triagem_previa and not await _triar(cfg, sessao, contexto):
        return

    sessao.anotar(
        "POLITICA",
        f"Liberado para contato — playbook <b>{tipo.playbook}</b>, canal WhatsApp.",
    )
    await _falar(cfg, sessao)


async def _triar(cfg: Settings, sessao: Sessao, contexto) -> bool:
    """Devolve `True` se a IA está liberada a falar. `False` = caso é do humano."""
    # ── Chave de teste: sem triagem, o pânico corre como remoção de bateria ──
    #
    # ⛔ **Decisão do Leonardo em 02/09/2026, e ela desliga uma proteção.**
    # Pedido literal: *"tire esse cálculo que está bagunçando o pânico, deixe
    # ele parecido com o evento de remoção de bateria, só que falando sempre de
    # acordo com o pânico"*.
    #
    # Dois motivos empurraram para cá, e nenhum é a triagem estar errada:
    #
    # 1. **Sem a plataforma da Bahrd, ela decide no escuro.** Um veículo fora
    #    dos três de `rastreamento/amostra.py` chega sem posição, rota nem
    #    histórico, e o prompt manda arredondar para cima diante de dado
    #    ausente. Todo pânico de teste pontuava alto.
    # 2. **Falhou em 8 dos 9 disparos do dia**, sempre no mesmo lugar: o
    #    raciocínio comia o orçamento e o JSON voltava vazio ou cortado.
    #
    # O que se perde: a IA passa a escrever para o motorista **sem nenhuma
    # avaliação prévia**. Se o botão foi apertado de verdade, a mensagem avisa
    # quem estiver do lado dele que a central percebeu. O `PB-PANICO` continua
    # regendo o tom da conversa; o que sumiu é o portão antes dela.
    #
    # `triagem_autoriza_encerrar` vai a `True` de propósito: sem nota, exigir
    # revisão humana do fechamento deixaria o caso preso na aba do operador —
    # que é justamente o que ele pediu para parar de acontecer.
    if not cfg.triagem_previa_ativa:
        sessao.triagem_autoriza_encerrar = True
        sessao.anotar(
            "POLITICA",
            "⚠️ <b>Triagem prévia desligada</b> (TRIAGEM_PREVIA_ATIVA=false) — modo "
            "de teste. A IA conduz este evento crítico <b>sem avaliação prévia</b>, "
            "como faria num evento comum.",
        )
        log.warning(
            "whatsapp_triagem_desligada",
            ocorrencia=sessao.ocorrencia_id,
            tipo=sessao.tipo.codigo,
        )
        return True

    sessao.anotar(
        "POLITICA",
        f"Evento crítico — <b>triagem obrigatória antes de qualquer contato</b>. "
        f"Limiar: {LIMIAR_ESCALONAMENTO}%.",
    )

    llm = construir_cliente_llm(cfg, sessao.modelo)
    try:
        # ⚠️ O span nasce **aqui**, e não dentro do `classificar`, porque quem
        # sabe de qual ocorrência isto é somos nós. Com a mesma `session.id` do
        # atendimento, a triagem aparece antes dos turnos na mesma conversa do
        # Langfuse, que é a ordem em que aconteceu.
        with span_da_triagem(
            sessao.tipo.codigo,
            Identificacao(
                ocorrencia=sessao.ocorrencia_id,
                telefone=sessao.telefone.replace("whatsapp:", ""),
                nome=sessao.dados.get("interlocutor"),
                placa=sessao.dados.get("placa"),
                origem=sessao.origem,
            ),
        ) as observado:
            triagem, custo = await triagem_panico.classificar(
                llm, contexto.resumo_para_triagem(), observado
            )
    except Exception as erro:  # noqa: BLE001 — falha vira humano, princípio 2
        log.warning("whatsapp_triagem_falhou", ocorrencia=sessao.ocorrencia_id, erro=str(erro))
        _encaminhar(
            cfg,
            sessao,
            "triagem_indisponivel",
            f"Triagem indisponível ({type(erro).__name__}). Nenhum contato foi feito.",
        )
        sessao.handoff = ["A triagem falhou. Nenhum contato foi feito."]
        return False
    finally:
        await llm.fechar()

    sessao.custo_usd += custo
    sessao.probabilidade_real = triagem.probabilidade_real
    sessao.anotar(
        "IA",
        f"Triagem: <b>{triagem.probabilidade_real}% de chance de ser real</b> · "
        f"{triagem.classificacao} · confiança {triagem.confianca}. "
        + " | ".join(triagem.evidencias),
    )

    if triagem.exige_humano:
        _encaminhar(
            cfg,
            sessao,
            "acima_do_limiar_de_risco",
            f"<b>{triagem.probabilidade_real}% ≥ {LIMIAR_ESCALONAMENTO}%</b> — caso de "
            "pessoa. <b>Nenhum contato automático foi feito.</b>",
        )
        sessao.handoff = [
            f"Estimou {triagem.probabilidade_real}% de chance de ser real — acima do limiar.",
            "Não mandou mensagem: em caso crítico acima do limiar o contato é seu.",
            *(f"Observou: {e}" for e in triagem.evidencias),
        ]
        return False

    sessao.triagem_autoriza_encerrar = triagem.pode_encerrar_sozinha

    if triagem.pode_encerrar_sozinha:
        destino = (
            f"<b>{triagem.probabilidade_real}% ≤ {LIMIAR_ENCERRAMENTO_AUTONOMO}%</b> com "
            "confiança alta — a IA atende e pode <b>encerrar sem operador</b>."
        )
        resumo = (
            f"Abaixo de {LIMIAR_ENCERRAMENTO_AUTONOMO}% com confiança alta — "
            "autorizada a encerrar sozinha depois de falar com a pessoa."
        )
    else:
        destino = (
            f"<b>{triagem.probabilidade_real}%</b> na faixa intermediária — a IA atende, "
            "e o fechamento passa pelo operador."
        )
        resumo = (
            f"Entre {LIMIAR_ENCERRAMENTO_AUTONOMO}% e {LIMIAR_ESCALONAMENTO}% — "
            "a IA atende, mas quem fecha é você."
        )

    sessao.anotar("POLITICA", destino)
    sessao.handoff = [
        f"Cruzou telemetria e histórico antes de falar · estimou "
        f"{triagem.probabilidade_real}% de chance de ser real.",
        resumo,
        *(f"Observou: {e}" for e in triagem.evidencias),
    ]
    return True


#: A despedida de quem pediu para falar com uma pessoa.
#:
#: Diferente da `despedida()` do catálogo, e por uma razão: aquela fecha um
#: caso resolvido, esta abre uma passagem. Quem pediu atendente precisa ouvir
#: três coisas — que foi entendido, que vai acontecer, e que não está sendo
#: largado. O `{nome}` sai vazio quando não se sabe o nome, e a frase continua
#: de pé.
#:
#: **Sem "obrigado pela paciência, viu?".** Saiu em 28/08/2026, a pedido do
#: Leonardo, lendo a frase no celular. Agradecer paciência sugere que a pessoa
#: esperou por algo, e ela não esperou: pediu um operador e está sendo passada
#: na hora. O "viu?" é vício de fala, alonga sem dizer nada, e ainda vinha com
#: "obrigado" no masculino numa persona feminina.
DESPEDIDA_PARA_HUMANO = (
    "Claro{nome}! Já estou passando o seu atendimento para um dos nossos "
    "operadores, e ele continua com você daqui. Qualquer coisa, a Bahrd "
    "Monitoramento está à disposição."
)

#: ⚠️ Ela não diz **como** o operador vai retomar, e isso é deliberado.
#:
#: Houve uma versão que prometia "ele vai te ligar", e ela saiu: **não
#: controlamos isso.** Quem pega o caso pode ligar, pode escrever no WhatsApp,
#: pode fazer os dois. Prometer o telefone deixaria a pessoa esperando uma
#: chamada que talvez venha como mensagem.
#:
#: Pelo mesmo motivo não há prazo: "em instantes" depende da fila, e a fila
#: não é nossa.


#: Quanto da fala do cliente cabe numa linha de trilha.
#:
#: A tela do operador é uma lista; uma colagem de 2.000 caracteres ali empurra
#: para fora tudo o que veio antes. O que ele precisa é reconhecer o pedido, e
#: para isso o começo basta.
LIMITE_DA_FALA_NA_TRILHA = 120


async def _entregar_a_um_humano(
    cfg: Settings,
    sessao: Sessao,
    pedido: str,
    ja_se_despediu: bool = False,
    fala: str = "",
) -> None:
    """O cliente pediu uma pessoa. Vai para a fila humana, sem discussão.

    **Escala mesmo com `ESCALONAMENTO_HUMANO_ATIVO` desligada**, e é o único
    caminho que faz isso. A chave existe para o caso em que a **IA** conclui
    que precisa de gente: nesta fase não há operador de plantão nem o dado da
    Bahrd para cruzar, e encher a fila de casos que ninguém vai olhar é pior do
    que registrar e fechar.

    Aqui o julgamento é de quem está do outro lado. Fechar o caso depois de
    dizer "já estou passando para um operador" seria mentir para o cliente e
    esconder o pedido de quem deveria recebê-lo — o defeito ficaria invisível
    exatamente para quem poderia corrigi-lo.

    Se não houver operador olhando o painel, o problema é esse, e ele precisa
    aparecer na fila para ser resolvido.
    """
    # A fala do cliente já entrou no histórico em `_continuar`; aqui só o que
    # ela provoca. Um relógio de silêncio pendente perde sentido: o caso saiu
    # das mãos da IA.
    cancelar_espera(sessao.ocorrencia_id)
    sessao.aguardando = False

    # ⚠️ **A trilha mostra o que ele escreveu, não o que o detector normalizou.**
    #
    # Em 28/08/2026 a linha saiu como «quero falar com uma pesoa». O cliente não
    # escreveu isso: o detector colapsa letras repetidas para pegar "pessooa" e
    # "aleeew", e era esse texto que ia para a tela. Na leitura do operador
    # aquilo vira erro de digitação do cliente, que é uma informação falsa sobre
    # uma pessoa.
    #
    # A expressão que disparou continua ali, porque é ela que serve para ajustar
    # as listas depois, mas separada e nomeada como o que é.
    escrito = sem_html(fala).strip()[:LIMITE_DA_FALA_NA_TRILHA]
    sessao.anotar(
        "CLIENTE",
        f"<b>Pediu para falar com uma pessoa</b> — ele escreveu «{escrito}»."
        if escrito
        else f"<b>Pediu para falar com uma pessoa</b> — disparou por «{pedido}».",
    )
    sessao.handoff.append(
        "⚠ O cliente <b>pediu atendimento humano</b>. Não foi a IA que desistiu: "
        "foi ele que pediu, e por isso o caso está aqui."
    )
    sessao.encerrar("pedido_de_atendimento_humano")
    sessao.escalada = True
    log.info(
        "whatsapp_pedido_de_humano",
        ocorrencia=sessao.ocorrencia_id,
        expressao=pedido,
        escalonamento_ativo=cfg.escalonamento_humano_ativo,
    )

    # ⚠️ Quando a IA escala pela marca, ela **já escreveu a despedida** e ela
    # já saiu. Mandar a nossa em cima produz duas mensagens de tchau seguidas,
    # que foi o que o cliente recebeu em 28/08/2026:
    #
    #     "Ok, Antônio, vou registrar aqui no sistema."
    #     "Claro, Antônio! Já estou passando o seu atendimento..."
    #
    # Aqui a frase existe para o caminho em que ninguém falou ainda: o pedido
    # explícito de atendente, detectado antes de o modelo ser chamado.
    # Quem puxa o próximo veículo é o `_fluxo`, olhando se esta conversa
    # terminou — assim vale para escalonamento, desfecho e o que mais fechar.
    if ja_se_despediu:
        return

    primeiro = _primeiro_nome(sessao)
    await _dizer(
        cfg, sessao, DESPEDIDA_PARA_HUMANO.format(nome=f", {primeiro}" if primeiro else "")
    )


# ══════════════════ O ramo "Está tudo bem!" e seus três caminhos ══════════════════
#
# Desenho dos gestores, doc 19. O cliente confirma que está tudo bem e a
# pergunta seguinte é **por quê** — porque "tudo bem" não fecha evento: fecha
# a causa, e a causa decide o que a Central faz com o alarme.
#
# Os três botões vão numa **mensagem interativa**, não num template. A
# diferença destrava o fluxo inteiro: template precisa de aprovação da Meta e
# vale para toda a base, mensagem interativa a IA manda na hora e muda quando
# quiser. Só funciona com a janela de 24 h aberta, que é o caso — a pessoa já
# respondeu ao template para chegar aqui.

#: `id` do botão → o que ele significa. O `id` é nosso e volta no webhook; o
#: rótulo é o que a pessoa lê, e a Meta corta em 20 caracteres.
BOTAO_MANUTENCAO = "causa_manutencao"
BOTAO_CHAVE_GERAL = "causa_chave_geral"
BOTAO_OUTRO_MOTIVO = "causa_outro_motivo"

PERGUNTA_DA_CAUSA = (
    "Que bom, {saudacao_curta}! Só preciso saber o motivo para registrar "
    "certinho aqui. Qual desses é o caso?"
)

CAUSAS: tuple[tuple[str, str], ...] = (
    (BOTAO_MANUTENCAO, "Em manutenção"),
    (BOTAO_CHAVE_GERAL, "Desliguei a chave"),
    (BOTAO_OUTRO_MOTIVO, "Outro motivo"),
)

#: Botões de causa do **pânico**. Ver `CAUSAS_POR_EVENTO`.
BOTAO_SEM_QUERER = "causa_acionamento_sem_querer"
BOTAO_NAO_FUI_EU = "causa_nao_fui_eu"

#: As causas mudam com o evento, e até 02/09/2026 não mudavam.
#:
#: ⚠️ **Num pânico o cliente tocou em «Está tudo bem!» e recebeu «Em manutenção
#: · Desliguei a chave · Outro motivo».** Nenhuma das três responde à pergunta
#: de um acionamento de emergência, e a do meio é sobre um equipamento que não
#: tem nada a ver com o caso.
#:
#: Os rótulos vieram do Leonardo, repassando a Central: «Acionei sem querer» e
#: «Outro motivo». O terceiro é sugestão nossa, e ganha o lugar por ser o único
#: que **muda o destino do caso**: quem diz que não foi ele está dizendo que
#: alguém ou alguma coisa acionou o alerta, e isso é de uma pessoa, não da IA.
#:
#: ⚠️ Estes botões são **mensagem interativa**, não template: saem na hora e
#: mudam quando quisermos. Os do cartão de abertura («Preciso de ajuda!» e
#: «Está tudo bem!») são do modelo aprovado na Meta e dependem de aprovação
#: para mudar. Ver `infra/templates-whatsapp/`.
CAUSAS_POR_EVENTO: dict[str, tuple[tuple[str, str], ...]] = {
    "PANICO": (
        (BOTAO_SEM_QUERER, "Acionei sem querer"),
        (BOTAO_NAO_FUI_EU, "Não fui eu"),
        (BOTAO_OUTRO_MOTIVO, "Outro motivo"),
    ),
}


def causas_do_evento(codigo: str) -> tuple[tuple[str, str], ...]:
    """Os botões de causa deste tipo de evento, ou os de sempre."""
    return CAUSAS_POR_EVENTO.get(codigo, CAUSAS)

#: O que o modelo lê quando o cliente escolhe uma causa. Um por ramo.
#:
#: Cada nota diz **o que apurar** e **onde parar** — e a segunda parte importa
#: tanto quanto a primeira. Sem ela o modelo fecha cedo, que foi o defeito de
#: 27/08 no botão de ajuda.
NOTA_POR_CAUSA: dict[str, str] = {
    BOTAO_MANUTENCAO: (
        "[O cliente TOCOU no botão «Em manutenção». O veículo está em manutenção, "
        "e isso já está confirmado: não pergunte de novo qual é a causa. "
        "Siga o passo 4 do seu playbook, que vale para este caso: as duas "
        "perguntas de manutenção, uma por mensagem. Quando ele autorizar, "
        "agradeça o contato e encerre com o desfecho veiculo_em_manutencao.]"
    ),
    BOTAO_CHAVE_GERAL: (
        "[O cliente TOCOU no botão «Desliguei a chave». Foi ele que desligou a "
        "chave geral, e isso já está confirmado: não pergunte de novo qual é a "
        "causa. Siga o passo 4b do seu playbook, que vale para este caso.]"
    ),
    BOTAO_OUTRO_MOTIVO: (
        "[O cliente TOCOU no botão «Outro motivo». Pergunte o que houve e "
        "entenda a causa. Se ele já explicou o suficiente para você contar o "
        "que houve, NÃO pergunte se pode encerrar: agradeça, diga qual foi o "
        "motivo e encerre. Pedir autorização para fechar o que já está "
        "explicado gasta um turno da pessoa à toa. Só pergunte quando ainda "
        "faltar alguma coisa. Antes de encerrar, siga o passo 4c do seu "
        "playbook: diga ao cliente o que a Central vai fazer com os avisos "
        "desse veículo. Depois agradeça o contato e use o desfecho "
        "outro_motivo_confirmado_pelo_cliente. IMPORTANTE: neste desfecho você "
        "PRECISA escrever, na sua mensagem, qual foi o motivo que ele deu — "
        "sem isso o caso não fecha e vai para uma pessoa revisar.]"
    ),
    BOTAO_SEM_QUERER: (
        "[O cliente TOCOU no botão «Acionei sem querer», num evento de pânico. "
        "Foi ele quem acionou, e foi sem querer: isso já está confirmado, não "
        "pergunte de novo quem foi nem se foi sem querer. NÃO use a palavra "
        "«botão» em momento nenhum. Siga o passo 5 do seu playbook: confirme de "
        "forma leve, PERGUNTE se pode registrar como acionamento sem querer e "
        "encerrar, e só depois do sim dele use o desfecho "
        "acionamento_acidental_confirmado.]"
    ),
    BOTAO_NAO_FUI_EU: (
        "[O cliente TOCOU no botão «Não fui eu», num evento de pânico. Ele está "
        "dizendo que NÃO acionou o alerta, e isso é sinal, não alívio: ou "
        "alguém acionou, ou o equipamento falhou. NÃO tente descobrir o que "
        "houve, NÃO faça mais perguntas e NÃO encerre. Escale imediatamente, "
        "com a marca de escalonamento, mantendo o tom normal da conversa.]"
    ),
}


#: O desfecho genérico do ramo "Outro motivo".
DESFECHO_OUTRO_MOTIVO = "outro_motivo_confirmado_pelo_cliente"

#: Quanto texto conta como "disse qual foi o motivo".
#:
#: Não é medida de qualidade — é medida de que **alguma coisa** foi escrita.
#: "Ok, encerrado!" tem 15 caracteres e não explica nada; qualquer frase que
#: conte o que houve passa disso com folga.
MINIMO_DO_MOTIVO = 40


def _motivo_escrito(mensagem: str) -> bool:
    """A IA disse qual foi o motivo, ou só fechou?"""
    return len(mensagem.strip()) >= MINIMO_DO_MOTIVO


#: A mensagem termina pedindo algo de volta?
#:
#: Olha só o **fim** do texto, e não qualquer `?` no meio: a IA legitimamente
#: recapitula antes de fechar ("você disse que foi sem querer, certo? Registrei
#: assim"), e ali a pergunta já foi respondida. O que trava o encerramento é a
#: mensagem **terminar** esperando resposta.
#:
#: Tolera aspas, parêntese e espaço depois do `?`, porque o modelo escreve como
#: gente e não como parser.
_TERMINA_EM_PERGUNTA = re.compile(r"\?[\s\"'”’)\]]*$")


def _termina_em_pergunta(mensagem: str) -> bool:
    return bool(_TERMINA_EM_PERGUNTA.search((mensagem or "").strip()))


#: Que tratativa cada desfecho gera no sistema da Bahrd.
#:
#: **Mapa fechado, e é ele a lista branca da regra combinada com a Bahrd.** A IA
#: propõe um desfecho; o catálogo diz se o desfecho existe; e este mapa diz o
#: que aquilo significa em ação. Em nenhum ponto o texto do cliente escolhe a
#: operação — ele só influencia qual desfecho a IA propõe, e desfecho fora da
#: lista já morre antes de chegar aqui.
#:
#: Desfecho que não está aqui simplesmente não gera ação, e isso é o normal:
#: Os desfechos terminados em `com_avisos_mantidos`, e o `local_e_base_do_cliente`,
#: fecham o caso e não mexem em nada: são exatamente os casos em que o cliente
#: **disse que prefere continuar sendo avisado**. Quem recusou não pode acabar
#: em silêncio.
#:
#: ⚠️ **É por isso que a IA pergunta em todos os caminhos.** Combinado com o
#: Leonardo em 28/08/2026, depois de ela informar em vez de perguntar num
#: atendimento de chave geral. A resposta do cliente vira o nome do desfecho, e
#: é o nome que decide a ação — nunca a narrativa do modelo.
TRATATIVA_POR_DESFECHO: dict[str, tratativas.Acao] = {
    "veiculo_em_manutencao": tratativas.Acao.INATIVAR_ENQUANTO_NO_LOCAL,
    # ⚠️ Só o desfecho COM autorização cria a regra permanente.
    #
    # Até 28/08/2026 `chave_geral_desligada_pelo_motorista` estava aqui, e um
    # atendimento fechou por ele sem a IA ter oferecido nada: a regra nasceu
    # assim mesmo. Regra de base vale para sempre e desliga o alarme daquele
    # local, então ela não pode depender de o modelo ter contado direito o que
    # combinou. O desfecho é que carrega a autorização.
    "chave_geral_com_regra_autorizada": tratativas.Acao.CRIAR_REGRA_DE_BASE,
    # A base do cliente é o outro caminho para a mesma regra permanente, e ele
    # ficou de fora até 28/08/2026: a IA prometia "sem avisos daqui pra frente"
    # e nenhum pedido saía. Ver a nota em `eventos.py`.
    "base_com_regra_autorizada": tratativas.Acao.CRIAR_REGRA_DE_BASE,
    # Chave geral sem regra permanente ainda precisa da supressão temporária: o
    # veículo continua parado no mesmo lugar com a chave desligada, e sem isto
    # ele dispara de novo em minutos. A diferença para o desfecho acima é o
    # prazo, não a existência: aqui vale enquanto ele estiver ali.
    "chave_geral_desligada_pelo_motorista": tratativas.Acao.INATIVAR_ENQUANTO_NO_LOCAL,
    # ⚠️ **A causa é outra; a situação do cliente é a mesma.**
    #
    # Entrou em 28/08/2026, depois de um atendimento real: o cliente contou que
    # tirou a bateria porque o suporte enferrujou e precisava soldar outro. A IA
    # agradeceu, registrou o motivo e encerrou. O veículo continuou parado no
    # mesmo lugar, com a bateria fora, e o alarme ia disparar de novo em
    # minutos.
    #
    # O ralo genérico existe para acolher causa que o catálogo não previu, não
    # para tratar o cliente pior do que os outros três ramos tratam.
    "outro_motivo_confirmado_pelo_cliente": tratativas.Acao.INATIVAR_ENQUANTO_NO_LOCAL,
    "reboque_autorizado": tratativas.Acao.INATIVAR_POR_PERIODO,
    "transporte_em_prancha_ou_balsa": tratativas.Acao.INATIVAR_POR_PERIODO,
}


#: O desfecho que tira este número dos avisos deste veículo.
#:
#: Constante, e não literal solto, porque o nome aparece em três lugares que
#: precisam concordar: a lista branca do catálogo, o gancho que grava o
#: bloqueio, e a aba do painel que filtra por ele.
DESFECHO_REMOCAO = "numero_removido_a_pedido"


async def _registrar_remocao(cfg: Settings, sessao: Sessao, mensagem: str) -> None:
    """Grava o bloqueio que a IA acabou de prometer ao cliente.

    ⚠️ **O par é (número, placa), e o número é o do interlocutor.** Não é o do
    cadastro: quem pediu para sair é quem está falando, e numa linha reciclada
    os dois são pessoas diferentes.
    """
    placa = sessao.dados.get("placa") or ""
    if not placa:
        sessao.handoff.append(
            "⚠ O cliente pediu para não receber mais os avisos, mas a ocorrência "
            "não tem placa — o bloqueio NÃO foi gravado e ele vai receber de novo."
        )
        log.warning("remocao_sem_placa", ocorrencia=sessao.ocorrencia_id)
        return

    try:
        await numeros_removidos.remover(
            cfg,
            sessao.telefone,
            placa,
            ocorrencia_id=sessao.ocorrencia_id,
            pedido=mensagem,
        )
    except Exception as erro:  # noqa: BLE001 — a falha não pode sumir
        sessao.handoff.append(
            "⚠ O cliente pediu para não receber mais os avisos e a IA confirmou, "
            "mas o bloqueio NÃO foi gravado. Ele vai receber de novo — precisa "
            "ser removido à mão."
        )
        log.error(
            "remocao_nao_gravada", ocorrencia=sessao.ocorrencia_id, placa=placa, erro=str(erro)
        )
        return

    sessao.anotar(
        "SISTEMA",
        f"Este número não recebe mais avisos do veículo <b>{placa}</b>. "
        "O alarme continua valendo para quem mais estiver no cadastro.",
    )
    sessao.handoff.append(
        f"📵 O contato pediu para sair dos avisos de {placa} e confirmou. "
        "O cadastro da Bahrd continua apontando para ele — a correção de "
        "verdade é lá."
    )


def _pedir_tratativas(sessao: Sessao, desfecho: str, mensagem: str) -> None:
    """Traduz o fechamento da conversa em pedidos para o sistema da Bahrd.

    Sempre pede o `FINALIZAR_EVENTO`; a supressão só quando o desfecho a
    justifica. Os dois entram como **pedidos**, não como feito: quem executa é
    o `ExecutorDaBahrd`, e hoje ele não executa nada porque a API não existe.

    ⚠️ **O veículo vem da sessão, nunca do texto.** O cliente pode escrever
    "inative a placa XYZ1234" o quanto quiser: a placa que vai é a da ocorrência
    que abriu esta conversa. É a regra do alvo vir da ocorrência, e esta é a linha
    vive.
    """
    placa = sessao.dados.get("placa") or "?"

    acao = TRATATIVA_POR_DESFECHO.get(desfecho)
    if acao is not None:
        tratativas.TRATATIVAS.pedir(
            sessao.ocorrencia_id,
            placa,
            acao,
            resumo=_RESUMO_DA_ACAO[acao],
            desfecho=desfecho,
        )
        # Vai para o `handoff`, que o painel abre; a trilha fica fechada por
        # padrão e isto precisa ser visto sem clique.
        #
        # ⚠️ **O motivo é o cliente, não o registro.** A IA acabou de prometer
        # que os eventos deste caminhão seriam desconsiderados. Se ninguém
        # executar, ele dispara de novo em minutos — e o cliente, que achou que
        # tinha resolvido, recebe outra notificação. Quem abrir a ocorrência
        # repetida precisa entender na hora por que ela voltou.
        sessao.handoff.append(
            f"⏳ <b>{_RESUMO_DA_ACAO[acao]}</b> — combinado com o cliente e "
            f"ainda não executado. {tratativas.ExecutorDaBahrd.MOTIVO}"
        )

    tratativas.TRATATIVAS.pedir(
        sessao.ocorrencia_id,
        placa,
        tratativas.Acao.FINALIZAR_EVENTO,
        resumo="Encerrar o evento no sistema da Bahrd",
        desfecho=desfecho,
    )


#: O que cada ação quer dizer, em português, para o operador ler sem decifrar.
_RESUMO_DA_ACAO: dict[tratativas.Acao, str] = {
    tratativas.Acao.INATIVAR_ENQUANTO_NO_LOCAL: (
        "Desconsiderar eventos deste veículo enquanto ele estiver neste local"
    ),
    tratativas.Acao.INATIVAR_POR_PERIODO: (
        "Desconsiderar eventos deste veículo por um período, em qualquer local"
    ),
    tratativas.Acao.CRIAR_REGRA_DE_BASE: (
        "Criar regra de base: este alarme não dispara neste local e horário"
    ),
    tratativas.Acao.FINALIZAR_EVENTO: "Encerrar o evento no sistema da Bahrd",
}


async def _perguntar_a_causa(
    cfg: Settings, sessao: Sessao, rotulo: str, abertura: str = ""
) -> None:
    """O cliente disse que está tudo bem. Falta saber **por quê**.

    "Tudo bem" não fecha evento. Uma remoção de bateria com o cliente tranquilo
    ainda é um caminhão sem rastreio, e o que a Central faz a seguir depende
    inteiramente da causa: manutenção suprime naquele local, chave geral pode
    virar regra permanente, e outro motivo fecha e pronto.

    Por isso a pergunta, e por isso ela é de botão: três toques cobrem o que
    três perguntas abertas levariam três turnos para apurar.
    """
    cancelar_espera(sessao.ocorrencia_id)
    sessao.aguardando = False

    sessao.registrar_cliente(rotulo)
    sessao.anotar("CLIENTE", f"Tocou em <b>«{rotulo}»</b> na notificação.")

    # ⚠️ **As causas mudam com o evento.** Num pânico, «Em manutenção · Desliguei
    # a chave» não responde nada, e foi o que o cliente recebeu em 02/09/2026.
    causas = causas_do_evento(sessao.tipo.codigo)
    primeiro = (sessao.dados.get("interlocutor") or "").split(",")[0].split(" ")[0]
    texto = sem_html(
        sem_travessao(PERGUNTA_DA_CAUSA.format(saudacao_curta=primeiro or "então"))
    )
    # A frase de volta, quando esta conversa estava na fila. Sem ela os botões
    # apareciam do nada, logo depois de o outro caminhão ser encerrado, e quem
    # lê não entende que o assunto mudou.
    if abertura:
        texto = f"{abertura} {texto}"
    texto = com_a_referencia(sessao, texto)

    try:
        cliente = ClienteMeta(cfg)
    except MetaIndisponivel as erro:
        # Sem botão a conversa não morre: a mesma pergunta em texto aberto
        # funciona, só custa um turno a mais para a IA classificar a resposta.
        log.warning("botoes_indisponiveis", erro=str(erro), ocorrencia=sessao.ocorrencia_id)
        await _falar(cfg, sessao)
        return

    try:
        anotar_mensagem_enviada(
            sessao,
            _id_da_resposta(
                await cliente.enviar_botoes(sessao.telefone, texto, list(causas))
            ),
        )
    except MetaIndisponivel as erro:
        log.warning("botoes_falharam", erro=str(erro), ocorrencia=sessao.ocorrencia_id)
        await _falar(cfg, sessao)
        return
    finally:
        await cliente.fechar()

    # Registrada como fala da IA para o painel mostrar a pergunta, e para o
    # modelo saber que ela já foi feita — senão o próximo turno pergunta de
    # novo o que a pessoa acabou de responder no botão.
    sessao.registrar_frase_com_botoes(texto, [r for _, r in causas])
    _ligar_relogio(cfg, sessao, sessao.tipo.silencio_no_texto_s, "sem resposta à causa")


async def _atender_causa(cfg: Settings, sessao: Sessao, ident: str, rotulo: str) -> None:
    """Uma das três causas foi escolhida. Daqui em diante quem conduz é a IA.

    O código não conduz a conversa: ele diz ao modelo **o que apurar e onde
    parar**, e sai da frente. A alternativa seria uma árvore de perguntas fixas,
    que é exatamente a URA que este projeto existe para não ser.
    """
    cancelar_espera(sessao.ocorrencia_id)
    sessao.aguardando = False

    sessao.causa_escolhida = ident
    sessao.registrar_cliente(rotulo, nota_para_o_modelo=NOTA_POR_CAUSA[ident])
    sessao.anotar("CLIENTE", f"Escolheu a causa <b>«{rotulo}»</b>.")

    await _falar(cfg, sessao)


async def _atender_pedido_de_ajuda(cfg: Settings, sessao: Sessao, rotulo: str) -> None:
    """O caminho do botão "Preciso de ajuda!" — **uma** mensagem, a da IA.

    Ela cumprimenta pela hora certa e entra na tratativa do evento. Nada de
    frase fixa antes: ver `NOTA_DO_BOTAO_DE_AJUDA` para o que aconteceu quando
    havia uma.

    A nota que acompanha o toque é a única coisa que o modelo lê a mais, e ela
    pode ir junto da fala do cliente **porque aqui o texto do cliente é nosso**
    — é o rótulo do botão que nós publicamos, não algo que ele digitou. Colar
    instrução ao lado de texto digitado seria abrir a porta que a
    `blindagem` existe para fechar.
    """
    # A pessoa respondeu: qualquer relógio de silêncio pendente perde sentido.
    cancelar_espera(sessao.ocorrencia_id)
    if sessao.aguardando:
        sessao.aguardando = False
        sessao.anotar("SISTEMA", "A pessoa voltou antes do prazo — espera cancelada.")

    sessao.pediu_ajuda = True

    # ⛔ **No pânico, o toque JÁ É o pedido de gente.** Decisão de 10/09/2026.
    #
    # Nos outros eventos a IA pergunta antes: "quer me contar o que houve ou
    # prefere que eu passe para um operador?". É a pergunta certa quando o pior
    # caso é uma bateria removida no pátio.
    #
    # No pânico não é. Quem toca em «Preciso de ajuda!» num alarme de emergência
    # já respondeu a pergunta, e devolvê-la custa um turno inteiro de espera
    # justamente no evento em que o tempo é o que se tem de mais caro. Pior: a
    # resposta pode nunca vir, porque quem está sob coação não digita.
    #
    # ⚠️ Vai para a fila **mesmo com `ESCALONAMENTO_HUMANO_ATIVO` desligada** —
    # `_entregar_a_um_humano` é o único caminho que faz isso, e é assim de
    # propósito: aqui o julgamento é de quem está do outro lado, não da IA.
    if sessao.tipo.codigo == "PANICO":
        sessao.registrar_cliente(rotulo)
        sessao.anotar(
            "CLIENTE",
            f"Tocou em <b>«{rotulo}»</b> num pânico — foi direto para atendimento "
            "humano, sem a pergunta que os outros eventos fazem.",
        )
        await _entregar_a_um_humano(cfg, sessao, pedido=rotulo, fala=rotulo)
        return

    sessao.registrar_cliente(
        rotulo,
        nota_para_o_modelo=NOTA_DO_BOTAO_DE_AJUDA.format(
            # O nome real, e não um marcador: o modelo copia melhor uma frase
            # pronta do que uma com lacuna para preencher.
            primeiro_nome=(sessao.dados.get("interlocutor") or "").split(",")[0].split(" ")[0]
            or "então",
        ),
    )
    sessao.anotar("CLIENTE", f"Tocou em <b>«{rotulo}»</b> na notificação.")

    await _falar(cfg, sessao)


async def _continuar(
    cfg: Settings,
    sessao: Sessao,
    corpo: str,
    em_audio: bool = False,
    ouvido: voz.Transcricao | None = None,
) -> None:
    """Registra a resposta da pessoa e devolve o próximo turno da IA."""
    if not corpo:
        return

    # ── Tentativa de virar o prompt ─────────────────────────────────────────
    #
    # Detectar não impede o ataque: o modelo já é instruído a recusar, e não
    # tem ferramenta nenhuma para executar o que quer que lhe peçam. O que isto
    # muda é **de quem é o caso**. Quem tenta virar o prompt não está pedindo
    # socorro por causa de um caminhão.
    #
    # A segunda tentativa é que escala, não a primeira: uma frase esquisita
    # solta é ruído, duas na mesma conversa são intenção — e escalar cedo demais
    # entrega ao humano um caso que a IA resolveria, que é o oposto da meta.
    sinal = blindagem.sinal_de_injecao(corpo)
    if sinal is not None:
        sessao.tentativas_de_injecao += 1
        sessao.anotar(
            "SEGURANÇA",
            f"Mensagem do cliente com sinal de manipulação de prompt: "
            f"<b>«{sinal}»</b> (tentativa {sessao.tentativas_de_injecao}).",
        )
        log.warning(
            "whatsapp_tentativa_de_injecao",
            ocorrencia=sessao.ocorrencia_id,
            sinal=sinal,
            tentativa=sessao.tentativas_de_injecao,
        )
        if sessao.tentativas_de_injecao >= 2:
            sessao.handoff.append(
                "⚠ O interlocutor tentou manipular as instruções da IA mais de "
                "uma vez. O caso saiu do automático por isso."
            )
            frase = _encaminhar(
                cfg,
                sessao,
                "manipulacao_de_instrucoes",
                "<b>Tentativa repetida de manipular as instruções da IA.</b> "
                "O conteúdo está na trilha; o caso é de uma pessoa.",
            )
            await _dizer(cfg, sessao, frase)
            return

    # Ela voltou antes do relógio: cancela o que estiver pendente. Sem isto, a
    # IA cobraria alguém que acabou de responder — e, desde 25/08, um pânico
    # respondido no quinto minuto ainda iria para o operador por silêncio.
    #
    # Incondicional de propósito: `aguardando` cobre só a retomada, e o relógio
    # do silêncio corre **antes** de existir qualquer "peraí". Cancelar o que
    # não existe é no-op.
    cancelar_espera(sessao.ocorrencia_id)
    if sessao.aguardando:
        sessao.aguardando = False
        sessao.anotar("SISTEMA", "A pessoa voltou antes do prazo — espera cancelada.")

    # Uma vez que a pessoa passou a falar, a conversa segue em áudio. Voltar
    # para texto no meio obrigaria alguém que está dirigindo a olhar a tela.
    if em_audio:
        sessao.canal = "AUDIO"

    # ⛔ A nota vai junto da fala porque aqui o texto do cliente E NOSSO: e a
    # palavra que o rodape do template ensinou, nao algo que ele redigiu.
    # Instrucao ao lado de texto digitado seria abrir a porta que a blindagem
    # existe para fechar.
    pediu_remocao = _pediu_remocao(corpo)
    sessao.registrar_cliente(
        corpo,
        transcrito=em_audio,
        duracao_s=ouvido.duracao_s if ouvido else None,
        nota_para_o_modelo=(
            NOTA_DE_PEDIDO_DE_REMOCAO.format(
                primeiro_nome=_primeiro_nome(sessao) or "Olá",
                placa=sessao.dados.get("placa") or "deste evento",
            )
            if pediu_remocao
            else None
        ),
    )
    if pediu_remocao:
        sessao.anotar(
            "CLIENTE",
            "Respondeu <b>REMOVER</b> — a IA vai pedir confirmação antes de "
            "tirar este número dos avisos do veículo.",
        )
    if ouvido is not None:
        sessao.anotar(
            "SISTEMA",
            f"Áudio de {ouvido.duracao_s:.0f}s transcrito · "
            f"confiança <b>{ouvido.confianca:.0%}</b>.",
        )

    # ── Pediu uma pessoa? Então vai falar com uma pessoa ────────────────────
    #
    # Depois de registrar a fala, para o operador abrir a conversa e ler o
    # pedido com as palavras dele. E **antes** de chamar o modelo, porque não
    # há o que perguntar: pedido explícito de atendente é a única fala do
    # cliente que não é matéria de opinião. Insistir depois de um pedido desses
    # é o que faz as pessoas odiarem URA.
    pedido = pedido_de_humano.pediu_humano(corpo)
    if pedido is not None:
        await _entregar_a_um_humano(cfg, sessao, pedido, fala=corpo)
        return

    if sessao.turnos_ia >= MAX_TURNOS_IA:
        # Acabaram os turnos. Se a triagem foi decisiva, a pessoa respondeu e
        # nada na conversa disparou escalonamento, o caso fecha aqui. Se a
        # triagem não autorizou, acabar os turnos continua sendo motivo para
        # um humano olhar — é a diferença entre "confirmado" e "não deu tempo".
        if cfg.panico_autonomo and sessao.pode_encerrar_sem_operador:
            sessao.anotar(
                "IA",
                "Turnos esgotados sem nada que contradissesse a triagem — encerrada "
                "com <b>alarme_falso_confirmado_por_triagem</b>.",
            )
            sessao.encerrar(
                "encerrada_pela_ia", desfecho="alarme_falso_confirmado_por_triagem"
            )
            await _dizer(
                cfg,
                sessao,
                atendimento_real.despedida_de_encerramento(
                    sessao.tipo.codigo, sessao.dados.get("interlocutor")
                ),
            )
            return

        _encerrar_sem_contato(cfg, sessao, f"limite de {MAX_TURNOS_IA} turnos")
        nome = (sessao.dados.get("interlocutor") or "").split(",")[0].split(" ")[0]
        despedida = (
            atendimento_real.despedida_de_encerramento(sessao.tipo.codigo, nome)
            if not sessao.escalada
            else "Vou te passar pra um colega meu aqui, só um instante."
        )
        await _dizer(cfg, sessao, despedida)
        return

    await _falar(cfg, sessao)


#: Tarefas de espera em curso, por ocorrência. Existe para poder cancelar
#: quando a pessoa responde antes do relógio — senão a IA cobraria alguém que
#: acabou de responder.
_ESPERAS: dict[str, asyncio.Task] = {}


def _encerrar_sem_contato(cfg: Settings, sessao: Sessao, motivo: str) -> None:
    """Fim das tentativas. Encerra com o desfecho do catálogo, ou encaminha.

    Quem decide é o catálogo, pelo `desfecho_sem_contato` do tipo de evento —
    não o modelo e não esta função. **Velocidade, bateria e movimento sem
    ignição** têm desfecho para silêncio: a orientação foi entregue, as
    tentativas estão registradas, e o desfecho diz exatamente o que aconteceu
    sem afirmar causa nenhuma.

    **Pânico e roubo ativo** não têm. Ali o silêncio é informação, e da pior
    espécie — nenhum desfecho honesto existe para "ninguém atendeu num pânico".
    Esses caem em `_encaminhar`, que decide entre operador e encerramento
    conforme a fase do projeto.
    """
    desfecho = sessao.tipo.desfecho_sem_contato

    if desfecho is None:
        _encaminhar(
            cfg,
            sessao,
            "sem_resposta_evento_critico",
            f"Sem resposta ({motivo}) em evento crítico — silêncio aqui não é "
            "ausência de informação.",
        )
        return

    sessao.anotar(
        "IA",
        f"Sem resposta ({motivo}). Encerrada pela IA com <b>{desfecho}</b> — "
        "a orientação foi entregue e nenhuma causa foi afirmada.",
    )
    sessao.encerrar("encerrada_pela_ia", desfecho=desfecho)
    log.info("whatsapp_encerrada_sem_contato", ocorrencia=sessao.ocorrencia_id, desfecho=desfecho)


#: O que o operador lê, aberto, quando a mensagem não chegou.
#:
#: Curto de propósito: vai para o bloco "O que a IA já fez", que fica aberto na
#: tela da ocorrência justamente para quem precisa saber em cinco segundos o que
#: não precisa refazer. O código de erro da Meta e o detalhe ficam na trilha de
#: auditoria, um clique abaixo, para quem for investigar.
#: Sem HTML: o bloco `handoff` é desenhado como **texto puro** no painel
#: (`{passo}` no `Ocorrencia.tsx`), então tag aqui apareceria literal na tela.
#: A trilha de auditoria, essa sim, aceita `<b>`.
FALHA_DE_ENTREGA = "⚠ A notificação NÃO foi entregue — {motivo}."

#: Desfecho de quem nunca foi alcançado. **Não é contenção.**
DESFECHO_NAO_CONTACTADO = "nao_contactado_falha_de_entrega"


def _registrar_falha_de_entrega(cfg: Settings, st: StatusDeEntrega) -> None:
    """A Meta avisou que a mensagem não chegou. Alguém precisa saber.

    **O buraco que isto fecha.** Até 26/08/2026 o aviso só ia para o log: não
    aparecia no painel, não anotava na ocorrência, não mudava desfecho. E, com
    os relógios de silêncio que entraram em 25/08, ele passou a produzir um
    desfecho **errado** — passadas as 24 h o caso encerrava como "cliente não
    respondeu", quando a verdade era "o cliente nunca recebeu nada".

    A diferença não é semântica. A meta da POC é conter ≥ 50% dos 8.000, e um
    caso em que ninguém foi alcançado contado como contenção deixa o número
    melhor que a realidade — o pior tipo de erro para levar a uma reunião.

    Note que a falha **síncrona** (a Meta recusa o envio na hora) já era tratada
    em `_dizer`, com `mensagem_nao_entregue`. Esta é a assíncrona: a Meta aceita,
    devolve 200, e a entrega falha segundos depois. Só o webhook conta.
    """
    # A guarda também aqui, e não só em quem chama: uma função chamada
    # "registrar falha" que encerra ocorrência com aviso de `delivered` seria
    # um estrago silencioso, e quem a chamasse de outro lugar não desconfiaria.
    if not st.falhou:
        return

    sessao = SESSOES.ativa(st.destinatario)
    if sessao is None:
        # Sem conversa viva não há o que anotar. O log já registrou o essencial.
        return

    # ⛔ **Escapado porque vem de fora.** `titulo` e `detalhe` são texto do
    # webhook da Meta, e o `handoff` é renderizado como HTML na tela da
    # ocorrência (o `<b>` dos outros itens depende disso). É a única
    # interpolação de terceiro nessa lista; todo o resto nasce aqui dentro.
    motivo = html.escape(st.titulo or st.detalhe or f"código {st.codigo}")
    sessao.handoff.append(FALHA_DE_ENTREGA.format(motivo=motivo))
    sessao.anotar(
        "SISTEMA",
        f"<b>A notificação não foi entregue.</b> Meta: {motivo}"
        + (f" (código {st.codigo})" if st.codigo else "")
        + (f" · {st.detalhe}" if st.detalhe and st.detalhe != motivo else ""),
    )

    # O relógio de silêncio perdeu o sentido: não se espera resposta de quem não
    # recebeu a pergunta.
    cancelar_espera(sessao.ocorrencia_id)

    # `_encaminhar` e não `encerrar`: ninguém foi alcançado, então isto não é
    # contenção. Com operador ativo o caso vai para uma pessoa; sem operador,
    # fecha registrando o motivo pelo qual teria ido. A frase que ela devolve é
    # descartada de propósito — falar de novo com um número que não recebe é
    # gastar template para nada.
    _encaminhar(
        cfg,
        sessao,
        DESFECHO_NAO_CONTACTADO,
        f"<b>A notificação não chegou ao cliente.</b> {motivo} — o evento segue "
        "sem contato, e nenhuma resposta virá deste número.",
    )
    log.warning(
        "whatsapp_ocorrencia_sem_contato",
        ocorrencia=sessao.ocorrencia_id,
        para=st.destinatario,
        codigo=st.codigo,
    )


def vigiar_silencio_apos_template(cfg: Settings, sessao: Sessao) -> None:
    """Liga o relógio do silêncio de quem **nunca** respondeu.

    Até 25/08/2026 este relógio não existia. O template saía, a sessão nascia, a
    requisição terminava — e acabou. Se o motorista não respondesse, nenhuma
    retomada acontecia, nenhum desfecho era gravado, ninguém era avisado, e a
    ocorrência ficava em "IA está fazendo" no painel até expirar em silêncio.

    Para bateria ou velocidade isso é aceitável e o catálogo já diz o desfecho.
    Para **pânico** não era: `_encerrar_sem_contato` existe exatamente para esse
    caso e diz, na própria docstring, que "silêncio aqui não é ausência de
    informação" — mas só era alcançada por quem já tinha falado ao menos uma
    vez. Quem nunca respondeu não entrava na máquina.

    Quem entra aqui é decidido pelo catálogo, via `silencio_no_texto_s`. Sem
    `if` de tipo de evento: se a Central criar amanhã outro evento em que o
    silêncio é sinal, basta o número no catálogo.
    """
    _ligar_relogio(
        cfg, sessao, sessao.tipo.silencio_no_texto_s, "sem qualquer resposta ao primeiro contato"
    )


#: Quanto a IA espera antes de insistir **na pergunta da autorização**.
#:
#: ⚠️ **Só nessa pergunta, e é decisão do Leonardo em 01/09/2026.** Nas outras
#: o prazo continua sendo o do catálogo, e o caso encerra sozinho passado o
#: dia. Insistir em toda pergunta seria a central cutucando quem não quis
#: responder; insistir nesta é buscar a única resposta que gera a tratativa.
#:
#: ⚠️ **Era 60 s, e 60 s é menos do que uma pessoa leva para responder.** Num
#: teste real em 02/09/2026 a IA perguntou às 16:43:27, cutucou às 16:44:27 e o
#: "Pode sim" chegou às 16:44:36, nove segundos depois do cutucão. Do lado de
#: quem recebe, a central perguntou duas vezes a mesma coisa enquanto ele
#: digitava a resposta.
#:
#: Não dá para saber se os 69 s foram a pessoa pensando ou a Meta demorando a
#: entregar, e para o prazo dá no mesmo: ele precisa caber nos dois. Três
#: minutos dão folga e continuam muito abaixo do dia inteiro do catálogo, que é
#: o prazo que esta constante existe para encurtar.
SILENCIO_NA_AUTORIZACAO_S = 180

#: O que denuncia a pergunta da autorização na última fala da IA.
#:
#: Os playbooks prescrevem «posso deixar os avisos desse veículo
#: desconsiderados enquanto...» e «posso deixar cadastrado...». O que as três
#: variantes têm em comum é o pedido de licença, e é por ele que se reconhece.
#:
#: ⚠️ Reconhecer por texto é frágil por natureza, e a alternativa seria pior:
#: um marcador que o modelo tivesse de emitir viraria mais uma coisa para ele
#: esquecer. Se um dia falhar, o pior caso é o prazo voltar a ser o do
#: catálogo — o mesmo de antes desta mudança.
_PEDIDO_DE_AUTORIZACAO = re.compile(r"\bposso deixar\b", re.IGNORECASE)


def espera_a_autorizacao(sessao: Sessao) -> bool:
    """A última coisa que a IA disse foi o pedido de autorização?

    É o que decide se o silêncio merece insistência ou o prazo normal.
    """
    ultima = next((f.texto for f in reversed(sessao.falas) if f.quem == "ia"), "")
    return bool(_PEDIDO_DE_AUTORIZACAO.search(ultima))


def vigiar_silencio_sem_aviso(cfg: Settings, sessao: Sessao) -> None:
    """Liga o relógio de quem estava conversando, foi perguntado e sumiu.

    **A terceira forma de silêncio, e a que ficou sem dono até 25/08/2026.** O
    relógio da retomada só liga quando o modelo marca `[AGUARDAR]`, e ele só
    marca quando a pessoa **anuncia** a pausa ("vou ver aqui"). Quem lê a
    pergunta, se distrai e não volta não anuncia nada — e é o caso mais comum
    de todos. Sem relógio, a ocorrência travava naquele ponto e sumia do painel
    um dia depois, sem desfecho, sem operador, sem entrar na conta da POC.
    """
    # ⭐ **Três minutos na pergunta da autorização, o prazo do catálogo no
    # resto.** É ela que gera a tratativa, e era a que mais ficava sem
    # resposta. Nas outras a IA não insiste: o caso encerra sozinho passado o
    # dia.
    #
    # ⚠️ **E só quando é a única conversa do número.** Com frota, a pessoa está
    # ocupada com outro caminhão: insistir aqui é cutucar quem está
    # respondendo outra coisa, e foi o que ele viu — *"está em loop perguntando
    # se eu quero desconsiderar, perguntou 2 vezes"*. Com mais de uma conversa
    # a pergunta sai **uma vez** e o prazo volta ao do catálogo; quem retoma o
    # assunto é o `_puxar_o_proximo_veiculo`, quando a vez chegar.
    sozinha = len(SESSOES.vivas(sessao.telefone)) <= 1
    if sessao.tipo.retoma_no_silencio and espera_a_autorizacao(sessao) and sozinha:
        _ligar_relogio(
            cfg, sessao, SILENCIO_NA_AUTORIZACAO_S, "sem resposta ao pedido de autorização"
        )
        return

    _ligar_relogio(
        cfg, sessao, sessao.tipo.silencio_sem_aviso_s, "sem resposta à última pergunta"
    )


#: Começo da linha de trilha que anuncia o fim por silêncio.
#:
#: Serve para reencontrá-la depois, e por isso mora aqui em vez de estar escrita
#: duas vezes.
_PREFIXO_DO_AVISO = "Sem resposta em "


def _ultimo_aviso_de_silencio(sessao: Sessao) -> str | None:
    """O último aviso de silêncio que já está na trilha, ou `None`.

    O relógio é rearmado a cada mensagem que a IA manda, e isso está certo: a
    contagem tem de começar da última fala, não da primeira. Anotar a cada
    rearme é que estava errado. Numa conversa de sete turnos a mesma frase
    aparecia quatro vezes, e empurrava para fora da tela do operador as linhas
    que ele precisa ver, o toque no botão, a causa escolhida, a tratativa.

    A trilha diz **o que vai acontecer se a pessoa sumir**, e isso só precisa
    ser dito de novo quando muda. Comparar o texto inteiro faz a regra sozinha:
    prazo diferente ou destino diferente é informação nova e entra; repetição
    idêntica não entra.
    """
    return next(
        (
            passo.descricao
            for passo in reversed(sessao.trilha)
            if passo.descricao.startswith(_PREFIXO_DO_AVISO)
        ),
        None,
    )


def _ligar_relogio(cfg: Settings, sessao: Sessao, segundos: int, motivo: str) -> None:
    """Agenda o fim do caso por silêncio, e conta na trilha o que vai acontecer.

    Quem entra e por quanto tempo é decidido pelo catálogo. Sem `if` de tipo de
    evento: se a Central criar amanhã outro evento em que o silêncio é sinal,
    basta o número lá.
    """
    if segundos <= 0 or sessao.encerrada:
        return

    destino = (
        "o caso vai para o operador — neste evento, silêncio é informação"
        if sessao.tipo.desfecho_sem_contato is None
        else f"o caso encerra com <b>{sessao.tipo.desfecho_sem_contato}</b>"
    )
    aviso = f"{_PREFIXO_DO_AVISO}{_legivel(segundos)}, {destino}."
    if aviso != _ultimo_aviso_de_silencio(sessao):
        sessao.anotar("SISTEMA", aviso)

    anterior = _ESPERAS.pop(sessao.ocorrencia_id, None)
    if anterior is not None:
        anterior.cancel()
    _ESPERAS[sessao.ocorrencia_id] = asyncio.create_task(
        _vigiar_silencio(cfg, sessao, segundos, motivo)
    )


def _legivel(segundos: int) -> str:
    """`300` → `5 min`. Trilha é lida por gente, não por quem conta segundos."""
    if segundos >= 3600:
        return f"{segundos // 3600} h"
    if segundos >= 60:
        return f"{segundos // 60} min"
    return f"{segundos}s"


async def _vigiar_silencio(cfg: Settings, sessao: Sessao, segundos: int, motivo: str) -> None:
    """Passou o prazo sem uma palavra. Fecha o caso **sem dizer nada.**

    `_encerrar_sem_contato` cuida do destino conforme o catálogo: no pânico
    escala para uma pessoa, nos demais encerra com o desfecho de "sem contato".
    Nenhum dos dois envia mensagem, e isso importa no pânico — se o botão foi
    apertado de verdade, escrever qualquer coisa agora avisa quem estiver do
    lado do motorista que a central percebeu, que é o que o `PB-PANICO` proíbe.

    A guarda é `ultima_em`, e não `houve_resposta`: este relógio serve tanto a
    quem nunca falou quanto a quem falou e sumiu. Qualquer movimento na sessão
    — dela ou da IA — invalida o prazo.

    E **não** confere `viva`. No caso de 24 h o relógio vence no mesmo instante
    em que a sessão expira; conferir aí faria o caso escapar por dois segundos
    de diferença e voltar a sumir sem registro, que é justamente o que se está
    consertando.
    """
    marca = sessao.ultima_em
    try:
        await asyncio.sleep(segundos)
    except asyncio.CancelledError:
        return

    _ESPERAS.pop(sessao.ocorrencia_id, None)

    if sessao.encerrada or sessao.ultima_em != marca:
        return

    # ── Quem está conversando não está em silêncio ──────────────────────────
    #
    # ⚠️ **"Do nada veio uma mensagem."** Leonardo, 01/09/2026. Ele estava
    # respondendo sobre o AKK4585 e o AAA4569 cutucou no meio, porque aquela
    # conversa estava parada há 60 s.
    #
    # O relógio olhava `sessao.ultima_em`, que é por conversa. Do lado de quem
    # recebe é tudo a mesma janela do WhatsApp: duas conversas cutucando quem
    # está no meio de uma terceira frase é a central falando sozinha.
    #
    # Reagenda em vez de desistir — o caso não pode sumir, só não é agora.
    ultima_do_numero = SESSOES.falou_conosco_em(sessao.telefone)
    if ultima_do_numero is not None and ultima_do_numero > sessao.ultima_em:
        log.info(
            "whatsapp_silencio_adiado",
            ocorrencia=sessao.ocorrencia_id,
            motivo="a pessoa está conversando em outra ocorrência deste número",
        )
        _ligar_relogio(cfg, sessao, segundos, motivo)
        return

    # ── Insistir antes de desistir ──────────────────────────────────────────
    #
    # ⚠️ **Só encerrar calado era perder a pergunta mais importante.** Num teste
    # de 01/09/2026 a conversa parou exatamente em *"posso deixar os avisos
    # desconsiderados enquanto ele estiver no local?"* — a pergunta que gera a
    # tratativa — e o sistema esperou 24 h para fechar sem desfecho.
    #
    # A máquina de retomada já existia e resolvia isso, mas só era alcançada
    # quando a pessoa **anunciava** a pausa ("peraí"). Quem lê e se distrai não
    # anuncia nada, e esse é o caso mais comum.
    #
    # ⚠️ **`retoma_no_silencio` é falso no pânico, e tem de continuar sendo.**
    # Se o botão foi apertado de verdade, escrever agora avisa quem estiver do
    # lado do motorista que a central percebeu. Ver `PB-PANICO`.
    # ⚠️ **Com frota, insiste UMA vez só.** Pedido do Leonardo em 01/09/2026.
    #
    # Um número com três caminhões em evento teria três conversas cutucando a
    # mesma pessoa, duas vezes cada: seis mensagens não pedidas, seis turnos de
    # modelo pagos, e um cliente irritado. O custo cresce com o número de
    # veículos, e a chance de resposta não.
    #
    # Com um veículo só a insistência continua valendo o que sempre valeu.
    #
    # ⚠️ **O teto só desce.** Calcular na hora tinha um furo, visto em produção
    # no mesmo dia: duas conversas rodaram juntas, uma encerrou, e a
    # sobrevivente virou "a única viva" e recuperou o orçamento de duas
    # insistências. O cliente levou a mesma pergunta duas vezes.
    #
    # ⚠️ **Com frota o teto é ZERO, e isso é decisão dele.** A pergunta sai uma
    # vez e pronto: quem está resolvendo outro caminhão não precisa ser
    # cutucado sobre este. Quem retoma o assunto é o `_puxar_o_proximo_veiculo`,
    # que fala quando a vez chega e sem custar mensagem extra.
    agora = 0 if len(SESSOES.vivas(sessao.telefone)) > 1 else sessao.tipo.retomadas_maximas
    teto = min(sessao.teto_de_retomadas, agora) if sessao.teto_de_retomadas else agora
    sessao.teto_de_retomadas = teto

    #
    # ⭐ **E só na pergunta da autorização.** Nas outras o silêncio encerra como
    # sempre encerrou: insistir em toda pergunta seria a central cutucando quem
    # simplesmente não quis responder.
    if (
        sessao.tipo.retoma_no_silencio
        and espera_a_autorizacao(sessao)
        and sessao.viva
        and sessao.retomadas < teto
    ):
        log.info(
            "whatsapp_silencio_retomando",
            ocorrencia=sessao.ocorrencia_id,
            tipo=sessao.tipo.codigo,
            segundos=segundos,
            retomada=sessao.retomadas + 1,
            teto=teto,
        )
        # `aguardando` porque é o que o `_retomar` confere para saber que a
        # espera ainda vale. Sem isto ele desiste na primeira linha.
        sessao.aguardando = True
        _ESPERAS[sessao.ocorrencia_id] = asyncio.create_task(
            _retomar(cfg, sessao, 0, ja_decorridos=segundos)
        )
        return

    log.warning(
        "whatsapp_silencio",
        ocorrencia=sessao.ocorrencia_id,
        tipo=sessao.tipo.codigo,
        segundos=segundos,
        motivo=motivo,
    )
    _encerrar_sem_contato(cfg, sessao, f"{_legivel(segundos)} {motivo}")

    # ── Desistir, mas não sumir ─────────────────────────────────────────────
    #
    # ⚠️ **"Ela encerrou do nada também."** Leonardo, 01/09/2026, olhando uma
    # conversa que parou no ar. A IA tinha perguntado, insistido uma vez e
    # fechado calada — do lado dele, a conversa simplesmente morreu.
    #
    # É o mesmo raciocínio que o `_agendar_retomada` já aplicava quando as
    # pausas anunciadas acabavam: *"fecha, mas não em silêncio"*. Faltava valer
    # aqui, no silêncio não anunciado, que é o caso mais comum.
    #
    # ⚠️ **Preso ao `retoma_no_silencio`, e por isso o pânico continua mudo.**
    # Se o botão foi apertado de verdade, escrever agora avisa quem estiver do
    # lado do motorista que a central percebeu. Ver `PB-PANICO`.
    #
    # ⚠️ **Só onde a IA tinha insistido**, que é a mesma condição da retomada.
    # No prazo de 24 h a janela da Meta fechou junto e a despedida não seria
    # entregue; e nas outras perguntas o fim calado é o comportamento de sempre.
    if sessao.tipo.retoma_no_silencio and espera_a_autorizacao(sessao):
        nome = (sessao.dados.get("interlocutor") or "").split(",")[0].split(" ")[0]
        await _dizer(
            cfg,
            sessao,
            "Vou te passar pra um colega meu aqui, só um instante."
            if sessao.escalada
            else f"Sem problema{', ' + nome if nome else ''}. Deixei o alerta "
            "registrado e os avisos continuam normais. Qualquer coisa é só me "
            "chamar por aqui!",
        )


async def _agendar_retomada(cfg: Settings, sessao: Sessao) -> None:
    """Marca de voltar a falar daqui a `proxima_espera_s`.

    **`asyncio` em processo, e isso é uma escolha de POC.** Reiniciar a API
    perde as esperas pendentes, e as conversas afetadas ficam paradas até a
    pessoa escrever. Em produção isso vira um job no arq/Redis, que já estão de
    pé — o comportamento é o mesmo, muda quem segura o relógio.
    """
    if not sessao.pode_retomar:
        # Última pausa: fecha, mas não em silêncio. A pessoa acabou de pedir um
        # tempo — sumir agora deixaria a conversa no ar do lado dela.
        _encerrar_sem_contato(cfg, sessao, f"{sessao.tipo.retomadas_maximas} retomada(s) usadas")
        await _dizer(
            cfg,
            sessao,
            "Beleza, já registrei aqui o que consegui. Qualquer coisa é só chamar!"
            if not sessao.escalada
            else "Vou te passar pra um colega meu aqui, só um instante.",
        )
        return

    segundos = sessao.proxima_espera_s
    sessao.aguardando = True
    sessao.anotar(
        "IA",
        f"A pessoa pediu um tempo. Aguardando <b>{segundos}s</b> antes de retomar "
        f"(retomada {sessao.retomadas + 1} de {sessao.tipo.retomadas_maximas}).",
    )
    log.info("whatsapp_aguardando", ocorrencia=sessao.ocorrencia_id, segundos=segundos)

    anterior = _ESPERAS.pop(sessao.ocorrencia_id, None)
    if anterior is not None:
        anterior.cancel()
    _ESPERAS[sessao.ocorrencia_id] = asyncio.create_task(_retomar(cfg, sessao, segundos))


def cancelar_espera(ocorrencia_id: str) -> None:
    """A pessoa voltou antes do relógio. Cobrança em cima disso é falta de educação."""
    tarefa = _ESPERAS.pop(ocorrencia_id, None)
    if tarefa is not None:
        tarefa.cancel()


async def _retomar(
    cfg: Settings, sessao: Sessao, segundos: int, ja_decorridos: int | None = None
) -> None:
    """Espera e volta a falar.

    `ja_decorridos` existe para quem chega aqui **depois** de o silêncio já ter
    passado — o `_vigiar_silencio` esperou o prazo dele e chama com `segundos=0`.
    Sem isto a trilha diria "passaram 0s sem resposta", que é falso e confunde
    quem for auditar o caso.
    """
    try:
        await asyncio.sleep(segundos)
    except asyncio.CancelledError:
        return

    _ESPERAS.pop(sessao.ocorrencia_id, None)
    if not sessao.viva or not sessao.aguardando:
        return

    sessao.aguardando = False
    sessao.retomadas += 1
    sessao.anotar(
        "SISTEMA",
        f"Passaram {ja_decorridos if ja_decorridos is not None else segundos}s "
        f"sem resposta — a IA retoma "
        f"({sessao.retomadas} de {sessao.tipo.retomadas_maximas}).",
    )

    # O aviso entra como contexto do sistema, não como fala do cliente: a
    # pessoa não disse nada, e inventar uma fala dela no histórico faria a IA
    # responder a algo que não aconteceu.
    sessao.historico.append(
        Mensagem(
            papel="user",
            conteudo=(
                "[sistema] A pessoa pediu um tempo e não voltou depois de "
                f"{segundos} segundos. Retome a conversa perguntando, de forma leve, "
                "se ela conseguiu verificar. Não repita a pergunta inteira e não "
                "cobre. Se ela continuar sem responder depois disso, escale."
            ),
        )
    )
    await _falar(cfg, sessao)


#: Um cumprimento vindo do cliente, em qualquer lugar da mensagem dele.
#:
#: Serve para uma coisa só: quando ele cumprimenta, a IA devolve, mesmo no meio
#: da conversa. Não responder um "boa noite" é grosseria, e nenhuma regra de
#: estilo vale isso.
_CUMPRIMENTO_DO_CLIENTE = re.compile(
    r"\b(?:bom\s+dia|boa\s+tarde|boa\s+noite|oi|ol[aá]|e\s*a[ií]|opa)\b",
    re.IGNORECASE,
)


def _ja_falou_com_ele(sessao: Sessao) -> bool:
    """A IA já se dirigiu a esta pessoa nesta conversa?

    A notificação do evento **não** conta: é voz do sistema, e quem responde a
    um alerta automático não estranha ser cumprimentado pela pessoa que aparece
    depois. Contam a pergunta com botões e qualquer turno anterior dela.
    """
    return any(f.quem == "ia" and f.tipo != "template" for f in sessao.falas)


def _sem_cumprimento_repetido(sessao: Sessao, mensagem: str) -> str:
    """Tira o "boa tarde" de abertura quando a conversa já começou.

    ⚠️ **Regra pedida três vezes no prompt e cumprida umas vezes sim, outras
    não.** Em 28/08/2026, no caminho dos botões, saiu «Boa noite, Antônio!»
    depois de a própria IA já ter escrito "Que bom, Antônio! Só preciso saber o
    motivo" e de o cliente ter tocado um botão.

    Mesma escolha do travessão e da saudação no fim: instrução é pedido, isto é
    garantia. Mas aqui a garantia é **condicional**, porque a saudação de
    abertura é o comportamento certo na primeira fala — e por isso a decisão
    mora aqui, onde se sabe o que já foi dito, e não dentro do `escrita.py`.

    A exceção que sobra: se a pessoa cumprimentou agora, a IA devolve. Não
    responder um "boa noite" é grosseria, e nenhuma regra de estilo vale isso.
    """
    if not _ja_falou_com_ele(sessao):
        return mensagem

    ultima = next((f.texto for f in reversed(sessao.falas) if f.quem == "cliente"), "")
    if _CUMPRIMENTO_DO_CLIENTE.search(ultima):
        return mensagem

    return sem_saudacao_no_inicio(mensagem)


async def _falar(cfg: Settings, sessao: Sessao) -> None:
    """Uma rodada: pede o turno ao modelo e entrega no celular.

    Falha aqui **nunca** vira silêncio: a pessoa está esperando resposta. Vira
    a frase de escalonamento e a sessão fecha para o operador assumir — que é o
    princípio 2 aplicado a um canal onde o cliente percebe a demora.

    ⚠️ O cérebro sai da **sessão**, não do `cfg`. A Central pode trocar o modelo
    quando as respostas ao cliente estiverem ruins, e a troca vale da próxima
    conversa em diante: quem já está falando termina no modelo em que começou.
    Ler do `cfg` aqui faria a troca pegar conversas no meio de um turno, com a
    triagem decidida por um modelo e a condução por outro.
    """
    llm = construir_cliente_llm(cfg, sessao.modelo)
    try:
        turno = await atendimento_real.proximo_turno(
            llm,
            sessao.tipo,
            sessao.canal,
            sessao.historico,
            # Como achar este atendimento depois. O que dali vira atributo de
            # trace é decidido em `observability/tracing.py`, junto da tranca
            # de conteúdo — daqui sai o que se sabe, não o que pode sair.
            Identificacao(
                ocorrencia=sessao.ocorrencia_id,
                telefone=sessao.telefone.replace("whatsapp:", ""),
                nome=sessao.dados.get("interlocutor"),
                placa=sessao.dados.get("placa"),
                # `turnos_ia` conta os que já saíram; este é o próximo. Quem
                # incrementa é o `registrar_ia`, e ele só roda depois que a
                # mensagem é entregue — então aqui o número ainda é o anterior.
                turno=sessao.turnos_ia + 1,
                origem=sessao.origem,
            ),
        )
    except Exception as erro:  # noqa: BLE001 — falha vira humano, princípio 2
        log.warning("whatsapp_turno_falhou", ocorrencia=sessao.ocorrencia_id, erro=str(erro))
        frase = _encaminhar(
            cfg,
            sessao,
            "falha_tecnica_no_atendimento",
            f"Atendimento interrompido ({type(erro).__name__}).",
        )
        await _dizer(cfg, sessao, frase)
        return
    finally:
        await llm.fechar()

    # ── O que a IA quer dizer sai daqui? ────────────────────────────────────
    #
    # Este é o único caminho que sobra depois de uma injeção bem-sucedida — e
    # ele é pior do que "a IA falar bobagem", porque **o número que envia é o
    # oficial verificado da Bahrd**. Uma mensagem com link é phishing com a
    # credibilidade da empresa; o cliente confia porque veio do número certo.
    #
    # Bloqueio, e não observação como o do guincho: aqui não há o que medir. A
    # IA nunca tem motivo para mandar link, para escrever seis linhas ou para
    # repetir a própria instrução. Qualquer um dos três é erro ou ataque, e nos
    # dois casos o certo é a mensagem não sair.
    problema = blindagem.problema_na_saida(
        turno.mensagem, prompts.blocos_de_sistema(sessao.tipo, sessao.canal)
    )
    if problema is not None:
        log.warning(
            "whatsapp_saida_bloqueada",
            ocorrencia=sessao.ocorrencia_id,
            motivo=problema,
            tamanho=len(turno.mensagem),
        )
        sessao.handoff.append(f"⚠ Uma resposta da IA foi barrada antes de sair: {problema}.")
        frase = _encaminhar(
            cfg,
            sessao,
            "saida_bloqueada",
            f"<b>Resposta da IA barrada antes do envio</b> — {problema}. "
            "O texto não chegou ao cliente e está no log.",
        )
        await _dizer(cfg, sessao, frase)
        return

    # ⛔ **A vigilância do guincho saiu daqui em 03/09/2026, com o dado.**
    #
    # Ela observava (sem bloquear) se a IA citava o guincho credenciado antes da
    # pessoa, porque nomear certo era a prova anti-roubo do PB-MOV-SEM-IGNICAO.
    # Não faz mais sentido por dois motivos, e o segundo sozinho já bastaria:
    # o nome não vai mais no contexto do modelo, e a Central não valida guincho
    # na tratativa real. Vigiar o vazamento de um dado que ninguém entrega, para
    # proteger uma conferência que ninguém faz, era manutenção sem beneficiário.
    mensagem = _sem_cumprimento_repetido(sessao, turno.mensagem)

    # ── Quem vai para uma pessoa não é o modelo quem anuncia ────────────────
    #
    # ⚠️ **"O roteamento no painel funcionou, mas a resposta foi errada para o
    # cliente."** Leonardo, 02/09/2026, num pânico. O caso foi para a fila
    # humana certinho, e o cliente leu:
    #
    #     "Obrigada, Antônio! Esse atendimento já foi encerrado e registrado
    #      aqui no sistema. Se precisar de mais alguma coisa, é só chamar a
    #      central."
    #
    # Ele tinha acabado de pedir uma pessoa. Recebeu "encerrado".
    #
    # ⭐ **É o mesmo princípio do desfecho: quem carrega o destino é o código.**
    # A tratativa nunca dependeu de o modelo narrar certo, e o encaminhamento
    # também não pode. O modelo decide **que** escala; a frase que descreve o
    # que vai acontecer é nossa, porque é a nossa que corresponde ao que o
    # sistema de fato fez.
    #
    # Calculado aqui, antes do envio, e reaproveitado no bloco de baixo: se as
    # duas contas ficassem separadas, elas divergiriam no primeiro ajuste.
    ultima_do_cliente = ""
    vai_para_uma_pessoa = False
    if turno.quer_escalar:
        ultima_do_cliente = next(
            (m.conteudo for m in reversed(sessao.historico) if m.papel == "user"), ""
        )
        vai_para_uma_pessoa = sessao.pediu_ajuda or pedido_de_humano.talvez_queira_humano(
            ultima_do_cliente
        )
        if vai_para_uma_pessoa:
            primeiro = _primeiro_nome(sessao)
            mensagem = DESPEDIDA_PARA_HUMANO.format(
                nome=f", {primeiro}" if primeiro else ""
            )

    # ⚠️ **Este caminho não passa pelo `_dizer`**, e por isso a referência e o
    # registro do id precisam estar aqui também. Descoberto num teste real de
    # 01/09/2026: a fala principal da IA saía **sem** o `[placa · evento]`
    # enquanto as despedidas e a pergunta de botões saíam com ele. Quem lia a
    # conversa via a IA identificar umas mensagens e outras não, que é pior que
    # não identificar nenhuma.
    mensagem = com_a_referencia(sessao, mensagem)
    sessao.registrar_ia(mensagem, turno.custo_usd, em_audio=sessao.canal == "AUDIO")

    entregue = await _responder(
        cfg, sessao.telefone, mensagem, em_audio=sessao.canal == "AUDIO"
    )
    anotar_mensagem_enviada(sessao, entregue)
    if not entregue:
        # Aqui a mensagem NÃO chegou, então não adianta mandar outra frase —
        # o canal está fora. Só registra e fecha.
        _encaminhar(
            cfg,
            sessao,
            "mensagem_nao_entregue",
            "<b>A mensagem não chegou ao cliente.</b> A IA escreveu a resposta, mas o "
            "canal recusou o envio — e a pessoa não sabe de nada.",
        )
        return

    if turno.quer_escalar:
        # ── Dois sinais fracos concordando valem um forte ───────────────────
        #
        # O modelo concluiu que precisa escalar. Se o que a pessoa acabou de
        # falar tem qualquer coisa a ver com gente, isso é pedido de atendente
        # e o caso vai para a fila humana — não fecha.
        #
        # Nasceu de uma falha real, 27/08/2026: o cliente escreveu "Quero falar
        # com algueém ai", com um `é` a mais. O caminho determinístico não
        # disparou por causa da digitação, **o modelo entendeu perfeitamente**,
        # e mesmo assim o caso foi fechado com "vou registrar aqui no sistema".
        # Duas leituras certas e um desfecho errado.
        #
        # Nenhuma das duas manda sozinha: `talvez_queira_humano` é permissiva
        # demais ("alguém mexeu na bateria" passa), e a conclusão do modelo
        # sozinha é o escalonamento comum, que a POC quer manter raro.
        # No ramo do «Preciso de ajuda!» a IA ofereceu a ligação, e quem aceita
        # responde curto: «sim», «pode ser», «isso». Nada disso um detector de
        # pedido de atendente reconhece, e sem esta marca o caso seria fechado
        # em vez de ir para a fila. A pergunta foi nossa; a resposta curta era
        # previsível.
        # `ja_se_despediu` porque a frase de encaminhamento **já saiu** logo
        # acima — e agora é a nossa, não a do modelo. Mandar outra seria o
        # cliente lendo dois tchaus seguidos, que já aconteceu em 28/08/2026.
        if sessao.pediu_ajuda:
            await _entregar_a_um_humano(
                cfg, sessao, "aceitou o operador", ja_se_despediu=True
            )
            return

        if vai_para_uma_pessoa:
            await _entregar_a_um_humano(
                cfg, sessao, "a IA entendeu como pedido de atendente", ja_se_despediu=True
            )
            return

        _encaminhar(
            cfg, sessao, "escalado_pela_ia", "Escalonamento pedido pela IA durante a conversa."
        )
        return

    # A pessoa pediu um tempo. A IA identifica a pausa; **quanto** esperar vem
    # do catálogo, nunca do modelo — senão ela escolheria meia hora num pânico.
    if turno.quer_aguardar:
        await _agendar_retomada(cfg, sessao)
        return

    # A IA propõe o desfecho; quem autoriza é o catálogo. Desfecho fora da lista
    # branca não fecha nada — vira escalonamento, que é o lado seguro do erro.
    if turno.desfecho_proposto:
        if eventos.desfecho_permitido(sessao.tipo.codigo, turno.desfecho_proposto):
            # Evento crítico na faixa do meio fecha com o operador, não sem ele.
            # O desfecho fica registrado como proposta — o trabalho da IA não
            # se perde, mas a assinatura é de uma pessoa.
            if sessao.fechamento_precisa_de_revisao or (
                sessao.tipo.exige_triagem_previa and not cfg.panico_autonomo
            ):
                _encaminhar(
                    cfg,
                    sessao,
                    turno.desfecho_proposto,
                    f"A IA propôs <b>{turno.desfecho_proposto}</b> em evento crítico fora "
                    "da faixa de encerramento automático.",
                )
                sessao.handoff.append(
                    f"Conduziu a conversa e propôs o desfecho «{turno.desfecho_proposto}»."
                )
                return

            # ⚠️ "Outro motivo" só fecha com o motivo escrito.
            #
            # Desfecho genérico é ralo por natureza: tudo que não encaixa nas
            # causas nomeadas passa a poder fechar por ali, e a estatística de
            # contenção perde sentido se ele virar a maioria. Exigir o motivo
            # em texto não impede o ralo — mantém ele **legível**, e é o que
            # permite descobrir, lendo a lista, qual causa apareceu tantas
            # vezes que merece nome próprio no catálogo.
            if turno.desfecho_proposto == DESFECHO_OUTRO_MOTIVO and not _motivo_escrito(
                turno.mensagem
            ):
                _encaminhar(
                    cfg,
                    sessao,
                    "outro_motivo_sem_justificativa",
                    "A IA fechou como <b>outro motivo</b> sem dizer qual — o caso vai "
                    "para revisão em vez de entrar na estatística como contido.",
                )
                log.warning(
                    "outro_motivo_sem_justificativa", ocorrencia=sessao.ocorrencia_id
                )
                return

            # ⛔ **Pergunta pendente cancela o encerramento.**
            #
            # Visto num pânico real, 03/09/2026, com o Gemini 2.5 Flash Lite. A
            # IA escreveu *"Então posso registrar como acionamento sem querer e
            # encerrar por aqui, Luciando?"* e emitiu a marca de encerrar **no
            # mesmo turno**. O código obedeceu a marca, o caso fechou, e a
            # pergunta chegou ao celular sem ninguém para responder.
            #
            # A contradição é do modelo, mas a detecção é nossa e não precisa de
            # modelo nenhum: quem pergunta ainda não decidiu. O playbook do
            # pânico manda **confirmar antes de fechar**, e um desfecho que sai
            # junto com a confirmação é o oposto disso.
            #
            # Não escala nem barra a mensagem: a pergunta é boa e vai para o
            # cliente. Só a marca é ignorada, e a conversa segue esperando a
            # resposta que ela pediu.
            if _termina_em_pergunta(turno.mensagem):
                sessao.anotar(
                    "POLITICA",
                    f"A IA propôs <b>{turno.desfecho_proposto}</b> na mesma mensagem em "
                    "que fez uma pergunta. O encerramento foi ignorado e o caso "
                    "continua aberto, esperando a resposta.",
                )
                log.warning(
                    "whatsapp_encerramento_com_pergunta_pendente",
                    ocorrencia=sessao.ocorrencia_id,
                    desfecho=turno.desfecho_proposto,
                    modelo=sessao.modelo,
                )
                return

            sessao.anotar(
                "IA",
                f"Encerrada pela IA — desfecho <b>{turno.desfecho_proposto}</b>, "
                "dentro da lista branca do playbook.",
            )
            sessao.encerrar(
                "encerrada_pela_ia",
                desfecho=turno.desfecho_proposto,
                horas_de_desativacao=turno.horas_de_desativacao,
            )
            _pedir_tratativas(sessao, turno.desfecho_proposto, turno.mensagem)
            # ⛔ O bloqueio é gravado DEPOIS de encerrar, e só aqui. A IA
            # confirmou com o cliente; se falhar em gravar, a promessa vira
            # mentira e ele recebe de novo amanhã — por isso a falha é ruidosa
            # no log e aparece no painel, em vez de morrer em silêncio.
            if turno.desfecho_proposto == DESFECHO_REMOCAO:
                await _registrar_remocao(cfg, sessao, turno.mensagem)
            log.info(
                "whatsapp_encerrada",
                ocorrencia=sessao.ocorrencia_id,
                desfecho=turno.desfecho_proposto,
            )
            # O próximo veículo é puxado pelo `_fluxo`, que olha se a conversa
            # terminou. Chamar aqui também faria a ponte disparar duas vezes.
        else:
            # Desfecho inventado pelo modelo morre aqui, nos dois modos. A
            # chave de configuração muda o destino do caso, **não** afrouxa a
            # lista branca — senão ela viraria porta lateral para fechar com
            # qualquer coisa.
            _encaminhar(
                cfg,
                sessao,
                "desfecho_recusado_fora_da_lista_branca",
                f"Desfecho <b>{turno.desfecho_proposto}</b> recusado — fora da lista branca.",
            )
            log.warning(
                "whatsapp_desfecho_recusado",
                ocorrencia=sessao.ocorrencia_id,
                desfecho=turno.desfecho_proposto,
            )
        return

    # Nada acima: a IA perguntou alguma coisa e ficou esperando. É o caso mais
    # comum de todos, e era o único sem relógio nenhum.
    vigiar_silencio_sem_aviso(cfg, sessao)
