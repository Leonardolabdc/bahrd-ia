"""Um turno da IA numa conversa com **gente de verdade**.

Diferença para :mod:`central_ia.agent.conversa`: lá os dois lados são gerados
pelo modelo, para exercitar o playbook sem incomodar ninguém. Aqui só a IA
fala — o outro lado é uma pessoa, e o turno dela chega pelo webhook.

Isso muda uma coisa importante: **não existe rebobinar**. Na simulação, um
turno ruim é descartado. Aqui ele já foi entregue no celular de alguém. Por
isso este módulo é conservador em dois pontos:

* resposta vazia não vira mensagem em branco — vira escalonamento;
* o histórico completo vai a cada chamada, em `messages`, nunca no bloco de
  sistema, para o cache de prompt continuar valendo (doc 02 §6.1).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import structlog

from central_ia.agent import prompts
from central_ia.agent.escrita import sem_saudacao_no_fim
from central_ia.agent.esforco import esforco_do_canal
from central_ia.domain.eventos import TipoEvento
from central_ia.observability.tracing import Identificacao, span_do_turno
from central_ia.ports.llm import (
    ClienteLLM,
    Esforco,
    Mensagem,
    OrcamentoDeTokensEstourado,
    RespostaVaziaDoModelo,
)

log = structlog.get_logger(__name__)

#: Teto de tokens de saída de um turno de conversa.
#:
#: ⚠️ **Era 400 e derrubou um atendimento em 28/08/2026.** No OpenRouter os
#: tokens de raciocínio saem deste mesmo orçamento, então um turno difícil
#: gasta tudo pensando e devolve conteúdo vazio. O turno que quebrou foi o do
#: cliente recusando a supressão dos avisos.
#:
#: 900 não é chute: a `blindagem` corta a fala da IA em 700 caracteres, uns 180
#: tokens, então sobram ~700 para o raciocínio. E teto alto não custa caro,
#: porque o que se paga é o token usado, não o reservado.
MAX_TOKENS_DO_TURNO = 900

#: Com quanto raciocínio tentar de novo quando o orçamento estourou.
#:
#: Baixo de propósito: a segunda tentativa não existe para pensar melhor,
#: existe para **responder**. Uma resposta simples chega ao cliente; um
#: silêncio, não.
ESFORCO_DA_SEGUNDA_TENTATIVA: Esforco = "low"

#: Marcas de controle. Ficam no fim da mensagem e são removidas antes do envio:
#: o cliente não pode ler código interno, e o sistema precisa saber o que a IA
#: decidiu. São marcas de texto porque este caminho ainda não tem tool calling
#: — quando tiver, viram chamadas de ferramenta e o parser some.
MARCA_ESCALONAMENTO = "[[ESCALAR]]"
MARCA_ENCERRAR = "[[ENCERRAR:"
MARCA_AGUARDAR = "[[AGUARDAR]]"

_ESCALAR = re.compile(re.escape(MARCA_ESCALONAMENTO), re.IGNORECASE)
#: `[[ENCERRAR:desfecho]]` ou `[[ENCERRAR:desfecho:4h]]`.
#:
#: ⭐ **O sufixo de horas existe por uma regra do gestor da Central**, de
#: 02/09/2026: num transporte, se o cliente disser quanto tempo leva, os
#: alarmes ficam suprimidos por esse tempo; se ele não souber, por duas horas.
#: Quem sabe a duração é quem está com o veículo, e antes disso não havia como
#: essa informação chegar do modelo até a supressão.
#:
#: Opcional de propósito: sem o sufixo vale o padrão do catálogo, que é o
#: comportamento de todos os outros desfechos.
_ENCERRAR = re.compile(
    r"\[\[ENCERRAR:\s*([a-z0-9_]+)\s*(?::\s*(\d{1,3})\s*h\s*)?\]\]", re.IGNORECASE
)
_AGUARDAR = re.compile(re.escape(MARCA_AGUARDAR), re.IGNORECASE)

#: Ênfase em Markdown, que o modelo produz por hábito.
#:
#: O WhatsApp usa `*um asterisco*` para negrito, não dois — então `**PLACA**`
#: chega literalmente com os asteriscos na tela do motorista. E no canal de
#: voz é pior: o TTS lê ou engasga no símbolo. Um atendente de central não
#: formata texto; a mensagem sai limpa.
_MARKDOWN = re.compile(r"\*{1,3}|_{2,3}|`+|^#{1,6}\s*", re.MULTILINE)

INSTRUCAO_DE_TURNO = """\
Você está numa conversa real, por WhatsApp, com a pessoa do outro lado. Cada
mensagem sua é entregue de verdade no celular dela — não há como voltar atrás.

Na PRIMEIRA mensagem que você escrever, abra com a saudação que veio no contexto
("Bom dia", "Boa tarde" ou "Boa noite") e o nome da pessoa — não com "Oi".
Central cumprimenta pelo período do dia, e você não sabe que horas são sem o
contexto.

Se o histórico já tiver a notificação automática, ela **não conta como sua
fala** — você ainda se apresenta e cumprimenta. Mas conta para o assunto: a
pessoa já leu ali o evento, a placa e o local, e está respondendo A ISSO. Entre
direto na tratativa, sem recontar o que ela acabou de ler. Repetir a notificação
é o erro mais visível que existe neste canal: quem acabou de ler a mensagem
percebe na hora que do outro lado ninguém sabe o que já foi dito.

⚠️ **A pergunta com botões, essa conta como sua fala.** Ela já chamou a pessoa
pelo nome, e vem marcada como sua no histórico. Depois dela você NÃO cumprimenta
de novo nem se apresenta: entra no assunto direto.

VOCÊ NÃO CONSULTA NADA. Não existe sistema para você olhar, não existe mapa
para você abrir, não existe cadastro para você buscar. Tudo o que você sabe
está neste contexto e nesta conversa, e nada mais vai chegar.

Então NUNCA diga que vai verificar, conferir, confirmar no sistema, olhar a
localização, checar o cadastro, dar uma olhada, consultar alguém ou "já
retorno". Você não vai, porque não tem como — e a pessoa fica esperando uma
resposta que nunca vem.

Quando faltar informação, a saída é uma só: PERGUNTE a ela. Ela é a única fonte
que existe do outro lado.

PENSE ANTES DE RESPONDER, e pense sobre a PESSOA, não sobre o roteiro.

**O que você pensa NÃO entra na mensagem.** Pensar é aqui dentro; o que sai é
só a fala pronta. Em 28/08/2026 a IA escreveu «Boa tarde... já cumprimentei.
Antônio, você costuma desligar a chave geral...» e mandou a própria dúvida
sobre cumprimentar para o celular do cliente.

Se estiver em dúvida entre dois jeitos de dizer, escolha um e escreva. Nunca
escreva os dois, nunca escreva a dúvida, nunca comente a sua própria decisão.

O playbook lista situações para você reconhecer, não é um menu onde a resposta
dela precisa caber. Antes de escrever, pergunte-se: o que ela quis dizer? o que
isso já responde do que eu precisava? o que ainda falta?

Quem diz "fui eu" já disse quem foi. Quem diz "tá na oficina" já disse onde
está. Quem diz "é uma moto" está te corrigindo, e tem razão. Em nenhum desses
casos você repete a pergunta: você usa o que ela deu e pergunta só o que falta.

Uma pessoa que responde e ouve a mesma pergunta de volta conclui, corretamente,
que do outro lado não tem ninguém prestando atenção. É o pior resultado
possível deste canal, pior do que errar: erro se corrige, e a impressão de
falar com uma máquina burra não.

Escreva APENAS a sua próxima mensagem. Nada de narrar o que está fazendo, nada
de descrever ações entre parênteses, nada de assinar. Uma ou duas frases.

Cumprimente **uma vez só**, e só se ainda não tiver falado com ela. Se já
existe uma fala sua nesta conversa, nada de "bom dia", "boa tarde" ou "boa
noite": a conversa já começou, e cumprimentar no meio dela é o sinal mais claro
de que ninguém leu o que veio antes.

A pergunta com botões conta como fala sua, e vem marcada assim no histórico. A
notificação automática do evento não conta: aquilo é voz do sistema, não sua.

A única exceção é ela cumprimentar você primeiro. Aí você devolve o
cumprimento dela, porque não responder seria grosseria.

E saudação **nunca fecha** mensagem. "Boa noite!" no fim de um atendimento é
cumprimento de chegada usado como tchau, e soa como despedida de quem estava
indo embora quando lembrou de falar. Para encerrar, diga o que ficou combinado
e pare.

Texto corrido, sem formatação. Nada de asterisco, negrito, título ou lista —
um atendente de central não formata texto, e o que você escrever vai ser lido
na tela de um celular ou falado em voz alta.

Três marcas de controle, sempre no FIM da mensagem:

- **{aguardar}** — A PESSOA pediu um tempo. Use quando ELA disser que vai
  verificar, olhar, perguntar para alguém, descer do caminhão, ligar para o
  patrão, ou qualquer coisa que signifique "já te respondo". Confirme com
  naturalidade ("beleza, fico no aguardo") e ponha a marca. Você será chamada
  de novo em alguns minutos para retomar. **Não escale nesses casos.**

  Esta marca é para a espera DELA, nunca para a sua. Você não tem o que
  esperar: não consulta nada, não processa nada em segundo plano. Se você
  escrever "só um segundo, vou confirmar aqui" e puser esta marca, a pessoa
  fica olhando a tela enquanto nada acontece do seu lado.
- **{escalar}** — o caso sai das suas mãos. **A mensagem inteira deste turno é
  esta frase, e mais nada:**

  > "{despedida}"

  Nada antes dela, nada depois. Não escreva uma despedida sua e emende esta em
  seguida: o cliente lê as duas, elas se contradizem, e ele fica sem saber o
  que vai acontecer.

  Nunca explique o motivo interno, nunca prometa retorno que não foi combinado,
  e **nunca prometa transferência**: quem recebe o caso depois é assunto da
  central, não da conversa.
- **{encerrar}desfecho]]** — o caso está resolvido. Antes, diga em uma frase
  simples que está tudo certo.

A diferença entre aguardar e escalar é a mais importante deste prompt:

| A pessoa diz | O que é | O que fazer |
|---|---|---|
| "vou verificar", "peraí", "já te falo", "deixa eu ver" | pausa | {aguardar} |
| "não sei", "não tô perto do veículo" | ela não tem a resposta | siga o playbook |
| "não desliguei nada", contradiz o sistema | negativa | {escalar} |
| relata assalto, medo, emergência | risco | {escalar} |

Quem pede um tempo não deu uma resposta ruim — não deu resposta ainda.
Escalar aí é entregar ao humano um caso que ia se resolver sozinho.

Se a pessoa não responder nada depois da espera, você recebe um aviso disso e
retoma perguntando se ela conseguiu verificar. Retome no máximo duas vezes; da
terceira em diante, {escalar}.

Desfechos autorizados neste evento — nenhum outro vale:
{desfechos}
"""


#: O que a IA diz quando o caso sai das mãos dela.
#:
#: Vem do código, não do playbook, porque depende de haver ou não um operador
#: para receber — e prometer "vou te passar pra um colega" quando não existe
#: colega é mentir para o cliente na última frase do atendimento.
#: ⚠️ Nenhuma das duas promete prazo. "Só um instante" saiu em 28/08/2026, pelo
#: mesmo motivo que "vou te ligar" já tinha saído: a conversa não controla
#: quando o colega pega o caso, e prazo que a gente não cumpre é pior do que
#: prazo nenhum.
DESPEDIDA_COM_OPERADOR = (
    "Vou passar o seu atendimento para um colega da Central, e ele continua com "
    "você por aqui."
)

#: ⚠️ **Sem operador não é sem consequência, e a frase precisa dizer isso.**
#:
#: Era *"Ok, {nome}, vou registrar aqui no sistema"*. Nos roteiros de 28/08 ela
#: foi a resposta a um cliente que disse **"não desliguei nada não"**, que na
#: Central é sinal de roubo, e a um cliente que pediu para ser deixado em paz.
#: Nos dois soou como se nada tivesse acontecido, porque "registrar" é o que se
#: diz de um caso que acabou.
#:
#: A frase nova diz a verdade do que acontece: fica anotado e a Central olha.
#: Não promete retorno, não promete prazo, e não finge que está resolvido.
DESPEDIDA_SEM_OPERADOR = (
    "Entendi, {nome}. Vou deixar tudo anotado aqui para a Central acompanhar. "
    "Qualquer coisa, é só me chamar por aqui."
)


#: Fuso da operação. A Bahrd atende só no Brasil, e o servidor roda em UTC —
#: saudar pelo relógio do servidor daria "boa tarde" às 22h de Curitiba.
FUSO_OPERACAO = ZoneInfo("America/Sao_Paulo")

#: A partir de que hora a madrugada incomoda.
#:
#: Um operador de verdade que fala com o motorista às 3h reconhece o horário —
#: *"desculpa o horário"* — e é isso que separa atendimento de robô. Fora dessa
#: faixa, pedir desculpa soaria esquisito.
MADRUGADA = range(0, 6)


def saudacao_do_momento(agora: datetime | None = None) -> str:
    """`Bom dia` · `Boa tarde` · `Boa noite`, pelo relógio de Brasília."""
    hora = (agora or datetime.now(FUSO_OPERACAO)).astimezone(FUSO_OPERACAO).hour
    if 5 <= hora < 12:
        return "Bom dia"
    if 12 <= hora < 18:
        return "Boa tarde"
    return "Boa noite"


def nota_do_horario(agora: datetime | None = None) -> str:
    """O que dizer sobre a hora, quando ela merece ser dita.

    Devolve vazio no horário normal — de propósito. Pedir desculpa às 14h
    chamaria atenção para nada, e a IA que se explica demais soa insegura.
    """
    hora = (agora or datetime.now(FUSO_OPERACAO)).astimezone(FUSO_OPERACAO).hour
    if hora in MADRUGADA:
        return "É madrugada para a pessoa — reconheça o horário com naturalidade."
    return ""


#: Como a IA se despede quando o caso fecha bem, por tipo de evento.
#:
#: **Por que não serve uma frase só.** "Boa viagem" pressupõe que a pessoa está
#: dirigindo. Num movimento sem ignição o caminhão está **no guincho**, e quem
#: atendeu pode nem estar perto dele; numa remoção de bateria ele costuma estar
#: parado em manutenção. Desejar boa viagem ali soa automático — e automático é
#: exatamente o que denuncia que não tem gente do outro lado.
#:
#: O padrão é neutro de propósito: serve para quem está dirigindo, parado no
#: posto ou olhando o caminhão subir na prancha.
_DESPEDIDA_PADRAO = "Tá certo então{nome}. Qualquer coisa é só chamar a gente!"

_DESPEDIDA_POR_EVENTO: dict[str, str] = {
    # Estes dois a pessoa está ao volante — aí a frase cabe.
    "VELOCIDADE_EXCEDIDA": "Tudo certo então{nome}. Boa viagem!",
    "ULTRAPASSOU_LIMITE_VELOCIDADE": "Tudo certo então{nome}. Boa viagem!",
    "VELOCIDADE_EXCEDIDA_CERCA_POLIGONO": "Tudo certo então{nome}. Boa viagem!",
    # Guincho ou transporte: o veículo não está sendo dirigido por ninguém.
    "MOVIMENTO_SEM_IGNICAO": (
        "Tá certo então{nome}, já deixei registrado aqui. Qualquer coisa é só chamar!"
    ),
    # Manutenção, oficina, veículo parado.
    "REMOCAO_BATERIA": (
        "Beleza{nome}, já registrei aqui. Qualquer coisa a gente está à disposição!"
    ),
}


def despedida_de_encerramento(codigo_evento: str, nome: str | None) -> str:
    """A última frase do atendimento, quando o caso fecha bem.

    Recebe o **código** do evento, não o tipo inteiro, para poder ser chamada
    de qualquer lugar sem arrastar o catálogo junto.
    """
    primeiro = (nome or "").split(",")[0].split(" ")[0].strip()
    molde = _DESPEDIDA_POR_EVENTO.get(codigo_evento, _DESPEDIDA_PADRAO)
    return molde.format(nome=f", {primeiro}" if primeiro else "")


def despedida(nome: str | None, com_operador: bool) -> str:
    if com_operador:
        return DESPEDIDA_COM_OPERADOR
    primeiro = (nome or "").split(",")[0].split(" ")[0]
    return DESPEDIDA_SEM_OPERADOR.format(nome=primeiro or "então").replace(", então,", ",")


def contexto_inicial(
    tipo: TipoEvento, dados: dict[str, str], com_operador: bool = True
) -> str:
    linhas = "\n".join(f"- {chave}: {valor}" for chave, valor in dados.items() if valor)
    desfechos = (
        "\n".join(f"- {d}" for d in tipo.desfechos_permitidos)
        or "- nenhum. Este evento sempre termina com uma pessoa: use a marca de escalonamento."
    )
    # A saudação vem do relógio de Brasília, não do modelo. Ele não sabe que
    # horas são — e "bom dia" às 22h é o tipo de erro que denuncia a máquina
    # antes da primeira pergunta.
    nota = nota_do_horario()
    return (
        "Contexto da ocorrência em atendimento:\n"
        f"- tipo de evento: {tipo.rotulo}\n"
        f"- criticidade: {tipo.criticidade}\n"
        f"- janela para escalonamento: {tipo.janela_s} segundos\n"
        f"- saudação correta para a hora de agora: {saudacao_do_momento()}\n"
        + (f"- {nota}\n" if nota else "")
        + f"{linhas}\n\n"
        + INSTRUCAO_DE_TURNO.format(
            escalar=MARCA_ESCALONAMENTO,
            encerrar=MARCA_ENCERRAR,
            aguardar=MARCA_AGUARDAR,
            despedida=despedida(dados.get("interlocutor"), com_operador),
            desfechos=desfechos,
        )
    )


class TurnoVazio(RuntimeError):
    """O modelo não produziu texto. Vira escalonamento, nunca mensagem vazia."""


@dataclass(frozen=True)
class Turno:
    mensagem: str
    quer_escalar: bool
    #: Desfecho que a IA propôs. **Proposta**, não decisão: quem valida contra a
    #: lista branca é o chamador, com o catálogo. Se a IA inventar um desfecho
    #: que não existe, ele morre ali.
    desfecho_proposto: str | None
    custo_usd: float

    #: Horas de supressão que o **cliente informou**, quando informou.
    #:
    #: `None` significa "ele não soube dizer", e aí vale o padrão do catálogo.
    #: Só tem efeito em desfecho que suprime por prazo; nos outros é ignorado.
    horas_de_desativacao: int | None = None

    #: A pessoa pediu um tempo. Quanto a IA espera é do catálogo, não do
    #: modelo — ele identifica a pausa, a política decide a duração.
    quer_aguardar: bool = False


async def proximo_turno(
    cliente: ClienteLLM,
    tipo: TipoEvento,
    canal: str,
    historico: list[Mensagem],
    quem: Identificacao | None = None,
) -> Turno:
    """`historico` já vem no formato do modelo.

    `user` é a pessoa, `assistant` é a IA, e a primeira entrada é o contexto da
    ocorrência.

    `quem` é só para observabilidade: agrupa os turnos numa conversa só e dá o
    rótulo pelo qual se acha o atendimento depois. Opcional porque nenhum turno
    pode deixar de acontecer por falta dele — e o que de dado pessoal sai dali
    quem decide é `observability/tracing.py`, não este módulo.
    """
    with span_do_turno(tipo.codigo, canal, quem) as observado:
        blocos = prompts.blocos_de_sistema(tipo, canal)
        try:
            resposta = await cliente.gerar(
                blocos_sistema=blocos,
                mensagens=historico,
                max_tokens=MAX_TOKENS_DO_TURNO,
                esforco=esforco_do_canal(canal),
            )
        except (OrcamentoDeTokensEstourado, RespostaVaziaDoModelo) as erro:
            # ⚠️ Segunda tentativa com menos raciocínio, e é a única do sistema.
            #
            # Falha real de 28/08/2026: no turno em que o cliente recusa a
            # supressão dos avisos, o modelo gastou o orçamento inteiro
            # pensando e não escreveu nada. Aumentar o teto ajuda e não basta,
            # porque o raciocínio se expande até onde couber; o que fecha o
            # buraco é pedir menos raciocínio quando o muito falhou.
            #
            # Uma tentativa só. Se a segunda também estourar, o caso é de
            # humano, e é assim que o `_falar` já trata.
            log.warning("turno_vazio_tentando_com_menos_esforco", erro=str(erro))
            resposta = await cliente.gerar(
                blocos_sistema=blocos,
                mensagens=historico,
                max_tokens=MAX_TOKENS_DO_TURNO,
                esforco=ESFORCO_DA_SEGUNDA_TENTATIVA,
            )

        bruto = resposta.texto or ""
        quer_escalar = bool(_ESCALAR.search(bruto))
        quer_aguardar = bool(_AGUARDAR.search(bruto))
        achado = _ENCERRAR.search(bruto)
        desfecho = achado.group(1).lower() if achado else None
        horas = int(achado.group(2)) if achado and achado.group(2) else None

        limpo = _AGUARDAR.sub("", _ESCALAR.sub("", _ENCERRAR.sub("", bruto)))
        mensagem = " ".join(_MARKDOWN.sub("", limpo).split())
        # Aqui, e não na entrega: o painel tem de mostrar ao operador o mesmo
        # texto que chegou ao celular. Ver `escrita.sem_saudacao_no_fim`.
        mensagem = sem_saudacao_no_fim(mensagem)

        if not mensagem:
            raise TurnoVazio(f"Resposta vazia do modelo (parada: {resposta.motivo_parada}).")

        # Escalar vence aguardar. Se o modelo pediu as duas — o que acontece
        # quando ele fica em cima do muro —, o lado seguro é entregar ao humano.
        if quer_escalar:
            quer_aguardar = False

        # Metadado sempre; conversa só onde `tracing` deixar. Passar `entrada` e
        # `saida` aqui não envia nada por si: a decisão mora em
        # `langfuse_com_conteudo`, e em produção ela é `False` sem exceção — ver
        # o cabeçalho de `observability/tracing.py`. Daqui, a chamada é a mesma
        # em todo ambiente, que é o ponto: nada de `if` de ambiente no agente.
        observado.registrar(
            modelo=resposta.modelo,
            tokens_entrada=resposta.uso.tokens_entrada,
            tokens_saida=resposta.uso.tokens_saida,
            tokens_cache=resposta.uso.tokens_cache_leitura,
            custo_usd=resposta.uso.custo_usd,
            desfecho_proposto=desfecho,
            quer_escalar=quer_escalar,
            quer_aguardar=quer_aguardar,
            versao_prompt=prompts.versao_dos_prompts(),
            entrada=historico,
            saida=bruto,
        )

        return Turno(
            mensagem,
            quer_escalar,
            desfecho,
            resposta.uso.custo_usd or 0.0,
            quer_aguardar=quer_aguardar,
            horas_de_desativacao=horas,
        )
