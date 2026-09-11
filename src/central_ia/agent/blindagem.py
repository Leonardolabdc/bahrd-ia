"""O que o cliente escreve, antes de virar contexto do modelo.

**A camada que de fato protege este sistema não está aqui — está na ausência de
ferramentas.** O contrato inteiro que o agente enxerga é
`gerar(blocos_sistema, mensagens, max_tokens, esforco) -> RespostaLLM`: sem
`tools`, sem `function_call`, sem acesso a banco, arquivo ou rede. Injeção de
prompt consegue fazer o modelo **dizer** coisas; não consegue fazê-lo **fazer**
coisas, porque não existe mecanismo. É por isso que a defesa mais forte da POC
é arquitetural e não uma lista de palavras proibidas.

Este módulo cuida do que sobra, e o que sobra é real:

* **Custo e disponibilidade.** Nada limitava o tamanho da mensagem que entra no
  prompt. Um texto de 200 KB colado no WhatsApp viraria ~50 mil tokens de
  entrada, a US$ 3/milhão — cinco reais numa mensagem, e o suficiente para
  estourar a janela do modelo e derrubar o atendimento. É o *sponge attack*
  aplicado a quem paga por token.
* **Intenção.** Quem tenta virar o prompt não está pedindo socorro por causa de
  um caminhão. Detectar isso não impede o ataque — o modelo já é instruído a
  recusar —, mas tira o caso das mãos da IA e põe numa pessoa, que é o lado
  seguro do erro.

**Detectar não é a trava; escalar é.** E escalar tem custo, então a segunda
tentativa é que escala, não a primeira: uma frase esquisita solta é ruído, duas
na mesma conversa são intenção.
"""

from __future__ import annotations

import re
import unicodedata

#: Teto de caracteres de uma mensagem de cliente que entra no prompt.
#:
#: 2.000 caracteres são ~500 tokens e cabem qualquer explicação honesta de
#: motorista com folga — a maior fala real medida até 26/08/2026 tinha 180.
#: Acima disso é colagem, não conversa.
#:
#: Cortar em vez de recusar: a pessoa pode estar num evento de verdade e ter
#: colado algo sem querer. O começo da mensagem é o que ela quis dizer.
LIMITE_ENTRADA = 2_000

#: Marca deixada no texto cortado, para o modelo não completar o que falta.
MARCA_DE_CORTE = " […mensagem cortada por tamanho]"

#: Sinais de tentativa de virar o prompt, em texto normalizado (sem acento,
#: minúsculo, espaços colapsados).
#:
#: São expressões de **várias palavras** de propósito. Palavra solta produz
#: falso positivo — "sistema", "instrução" e "ignorar" aparecem em conversa
#: honesta de central o tempo todo, e um falso positivo aqui manda para o
#: humano um caso que a IA resolveria.
_SINAIS = (
    # Anular a instrução
    "ignore as instrucoes",
    "ignora as instrucoes",
    "ignore todas as instrucoes",
    "esqueca as instrucoes",
    "esqueca tudo",
    "desconsidere as instrucoes",
    "ignore previous instructions",
    "disregard your instructions",
    # Revelar o prompt
    "prompt de sistema",
    "system prompt",
    "suas instrucoes",
    "mostre as instrucoes",
    "repita as instrucoes",
    "qual e o seu prompt",
    "print your instructions",
    "reveal your prompt",
    # Trocar de papel
    "modo livre",
    "modo desenvolvedor",
    "developer mode",
    "a partir de agora voce e",
    "agora voce e um",
    "finja que voce e",
    "voce nao e mais",
    "act as if you",
    "you are now",
    # Fingir autoridade
    "nova ordem do sistema",
    "instrucao do administrador",
    "mensagem do desenvolvedor",
    # Marcadores de papel, que só existem em ataque
    "<|im_start|>",
    "<|im_end|>",
    "[inst]",
    "###instruction",
    "system:",
    "assistant:",
    # Sondagem de banco — não há ferramenta, mas quem tenta se declara
    "select * from",
    "drop table",
    "delete from",
    "union select",
    "' or '1'='1",
)

_ESPACOS = re.compile(r"\s+")


def _normalizar(texto: str) -> str:
    """Minúsculo, sem acento, espaços colapsados.

    Sem isto, `IGNORE  AS  INSTRUÇÕES` passaria por três motivos diferentes ao
    mesmo tempo — e escrever variante de cada um na lista é corrida perdida.
    """
    sem_acento = unicodedata.normalize("NFKD", texto.lower())
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return _ESPACOS.sub(" ", sem_acento)


def truncar(texto: str) -> str:
    """Corta a mensagem no teto. Devolve igual quando cabe."""
    if len(texto) <= LIMITE_ENTRADA:
        return texto
    return texto[:LIMITE_ENTRADA].rstrip() + MARCA_DE_CORTE


def sinal_de_injecao(texto: str) -> str | None:
    """O sinal encontrado, ou `None`. Não decide nada — quem decide é a rota.

    Devolve **qual** sinal bateu, e não só `True`, porque isso vai para a trilha
    da ocorrência: o operador que receber o caso precisa ver o que a pessoa
    escreveu de estranho, não uma acusação sem prova.
    """
    normalizado = _normalizar(texto)
    return next((sinal for sinal in _SINAIS if sinal in normalizado), None)


# ─────────────────────── O outro lado: o que a IA escreve ───────────────────────
#
# O caminho de saída é mais perigoso do que parece, e por um motivo que não tem
# a ver com o modelo: **o número que envia é o oficial verificado da Bahrd**.
#
# Uma injeção que faça a IA escrever "acesse http://bahrd-monitoramento.co para
# regularizar" é phishing com a credibilidade da empresa — o cliente confia
# porque a mensagem veio do número certo, com o nome certo. Isso é bem pior que
# a IA falar bobagem.
#
# O segundo caso é a IA repetir o próprio prompt. Ali estão o playbook e os
# limiares de escalonamento: entregar isso ensina o atacante o que dizer para
# obter o desfecho que ele quer na próxima tentativa.
#
# Os dois são detectáveis de forma determinística, sem perguntar a modelo nenhum.

#: Teto de caracteres de uma mensagem da IA.
#:
#: O `canal_wa_texto` pede "uma a três linhas". 700 caracteres são umas seis, já
#: com folga para um evento que exija explicação. Acima disso não é conversa de
#: central: ou é despejo de prompt, ou é o modelo perdido.
LIMITE_SAIDA = 700

#: Endereço de internet em qualquer forma que o WhatsApp transforme em link.
#:
#: A IA **nunca** tem motivo para mandar link. O template aprovado já leva os
#: botões de loja de aplicativo, e o corpo dele diz "acesse o app da Bahrd" sem
#: URL nenhuma. Link em mensagem livre só aparece por erro ou por ataque.
#: Três regras, e a terceira é a que não envelhece:
#:
#: 1. esquema explícito — `http://`, `https://`
#: 2. `www.` no começo
#: 3. **qualquer `dominio.tld/`** — encurtador novo aparece toda semana e
#:    perseguir lista de TLD é corrida perdida; a barra é o que denuncia
#:
#: A barra é exigida na terceira porque sem ela `obrigada.Qualquer coisa` viraria
#: link — em português, ponto seguido de letra é frase, não domínio.
_LINK = re.compile(
    r"(?:https?://"
    r"|\bwww\."
    r"|\b[a-z0-9-]{2,}\.[a-z]{2,12}/"
    r"|\b[a-z0-9-]+\.(?:com|net|org|br|io|co|app|link|info|xyz|me|site|online|shop)\b)",
    re.IGNORECASE,
)

#: Tamanho do trecho que denuncia repetição do prompt.
#:
#: 60 caracteres seguidos, idênticos a um pedaço da **regra**, não acontecem por
#: acaso. Menos que isso pegaria frase comum ("o alerta encerra por aqui") e
#: mandaria atendimento bom para o operador.
_TRECHO_DELATOR = 60

#: Linha de citação markdown. É como os playbooks marcam **o que a IA deve
#: dizer**: `> "Oi, Bruno, é a assistente virtual da Bahrd…"`.
#:
#: A convenção é do próprio projeto, e é o que torna esta separação possível
#: sem anotar nada de novo nos prompts — o marcador já existia, faltava lê-lo.
_LINHA_DE_EXEMPLO = re.compile(r"^\s*>.*$", re.MULTILINE)

#: E o exemplo embutido no meio de um parágrafo.
#:
#: ⚠️ **As guilhemetas atravessam linha; as aspas não.** A diferença veio de um
#: atendimento real em 28/08/2026: os playbooks prescrevem frases inteiras com
#: «...», e o texto quebra em 80 colunas como todo o resto do arquivo. Com o
#: `\n` proibido, a frase prescrita continuava contando como regra, e a IA
#: dizendo **exatamente o que mandamos dizer** era barrada por vazamento.
#:
#: `«»` são pares que não aparecem soltos, então casar através de linha é
#: seguro. Aspas retas e curvas aparecem soltas o tempo todo, e liberar a quebra
#: nelas faria uma aspa perdida engolir parágrafos inteiros de regra.
_EXEMPLO_EMBUTIDO = re.compile(
    r"«[^«»]{10,400}»"
    r"|[\"“][^\"“”\n]{10,300}[\"”]"
)


def _so_as_regras(blocos_sistema: list[str]) -> str:
    """A instrução **sem** as falas de exemplo. É contra isto que se compara.

    **A distinção que faz esta checagem funcionar.** Os playbooks trazem
    frases prontas para a IA usar — *"Oi, João! Aqui é a assistente virtual da
    Bahrd…"*, 154 caracteres. Usar uma dessas é obedecer, e a versão anterior
    lia como vazamento: qualquer abertura de conversa batia com o exemplo e a
    mensagem era barrada.

    Aconteceu em 27/08/2026, num atendimento real. A IA escreveu 81 caracteres,
    a saída foi bloqueada, e o cliente recebeu a despedida de escalonamento em
    vez de uma conversa. **Falso positivo sem sintoma visível** — o log dizia
    "repetia um trecho literal da instrução", que estava tecnicamente certo e
    operacionalmente errado.

    Subir o limiar não resolveria: o exemplo mais longo tem 154 caracteres, e
    acima disso a checagem deixaria passar vazamento de verdade. A separação
    não é de tamanho, é de natureza — **pode repetir o que mandamos dizer,
    nunca as regras de como se comportar.**
    """
    texto = "\n".join(blocos_sistema)
    texto = _LINHA_DE_EXEMPLO.sub(" ", texto)
    return _normalizar(_EXEMPLO_EMBUTIDO.sub(" ", texto))


def vazou_o_prompt(resposta: str, blocos_sistema: list[str]) -> bool:
    """A resposta contém um pedaço literal das **regras**?

    Compara texto normalizado contra os blocos de sistema **reais** daquela
    chamada, e não contra uma lista de frases escrita à mão: assim continua
    valendo quando os prompts forem reescritos, que é o que sempre acontece.
    """
    alvo = _normalizar(resposta)
    if len(alvo) < _TRECHO_DELATOR:
        return False

    regras = _so_as_regras(blocos_sistema)
    return any(
        alvo[i : i + _TRECHO_DELATOR] in regras
        for i in range(len(alvo) - _TRECHO_DELATOR + 1)
    )


def problema_na_saida(resposta: str, blocos_sistema: list[str]) -> str | None:
    """O que há de errado com o que a IA quer dizer, ou `None`.

    Devolve o motivo em texto porque ele vai para a trilha da ocorrência: o
    operador que receber o caso precisa saber **por que** a mensagem foi barrada,
    não só que foi.
    """
    if _LINK.search(resposta):
        return "a mensagem continha um link, e a IA nunca manda link"
    if len(resposta) > LIMITE_SAIDA:
        return f"a mensagem tinha {len(resposta)} caracteres, acima do teto de {LIMITE_SAIDA}"
    if vazou_o_prompt(resposta, blocos_sistema):
        return "a mensagem repetia um trecho literal da instrução do sistema"
    return None
