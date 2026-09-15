"""Ajustes de escrita aplicados a tudo que sai para o cliente.

Existe porque instrução de prompt é pedido, não garantia. O `persona_core`
manda não usar travessão e os prompts foram limpos dele em 24/08 — o modelo
imita o estilo do que lê —, mas um escorregão numa mensagem entregue não tem
volta. Aqui é onde vira certeza.

Ninguém digita travessão no WhatsApp. Ele é marca de texto redigido, e texto
redigido é o que denuncia que do outro lado tem uma máquina.
"""

from __future__ import annotations

import re

#: Travessão e traço médio. O hífen comum (`-`) não entra: ele é digitado por
#: gente o tempo todo, em placa, em telefone, em nome de rua.
_TRACOS = "—–"

#: Depois destes, vírgula ficaria errado. Nestes casos o travessão vira só o
#: espaço que já separava as duas partes.
_PONTUACAO_FORTE = ".!?:;,"

_ABRINDO_LINHA = re.compile(rf"^(\s*(?:[-*>]\s*)?)[{_TRACOS}]\s*")
_NO_MEIO = re.compile(rf"\s*[{_TRACOS}]\s*")
_VIRGULA_DOBRADA = re.compile(r",\s*,")
_ESPACO_ANTES_DA_PONTUACAO = re.compile(r"\s+([,.;:!?])")


def sem_travessao(texto: str) -> str:
    """Troca travessão por vírgula, que é a pausa equivalente em português.

    Linha por linha, porque o tratamento do começo da linha é diferente: ali o
    travessão costuma ser marcador de item ou de fala, e o certo é sumir com
    ele, não virar uma vírgula solta abrindo a frase.

    Idempotente: rodar duas vezes dá o mesmo resultado. É por isso que dá para
    chamar tanto no registro quanto na entrega sem medo.
    """
    if not texto or not any(t in texto for t in _TRACOS):
        return texto

    saida = []
    for linha in texto.split("\n"):
        limpa = _ABRINDO_LINHA.sub(r"\1", linha)

        def _troca(m: re.Match[str], origem: str = limpa) -> str:
            antes = origem[: m.start()].rstrip()[-1:]
            return " " if not antes or antes in _PONTUACAO_FORTE else ", "

        limpa = _NO_MEIO.sub(_troca, limpa)
        limpa = _VIRGULA_DOBRADA.sub(",", limpa)
        limpa = _ESPACO_ANTES_DA_PONTUACAO.sub(r"\1", limpa)
        # Travessão no fim da linha vira vírgula pendurada; melhor não deixar.
        saida.append(re.sub(r",\s*$", "", limpa).rstrip())

    return "\n".join(saida)


#: Qualquer coisa entre `<` e `>`, mais entidade HTML já escapada.
#:
#: O segundo padrão importa: sem ele, `&lt;script&gt;` atravessaria intacto e o
#: navegador o desenharia como tag depois de decodificar.
_TAG = re.compile(r"<[^>]*>")
_ENTIDADE = re.compile(r"&(?:#x?[0-9a-fA-F]+|[a-zA-Z][a-zA-Z0-9]{1,31});")


def sem_html(texto: str) -> str:
    """Remove marcação HTML do que o modelo escreveu. **Trava, não pedido.**

    **O caminho que isto fecha: cliente → modelo → navegador do operador.**

    O painel desenha o briefing da ocorrência com `dangerouslySetInnerHTML`, e
    numa sessão real esse briefing é a última fala da IA — texto do modelo. Um
    cliente que convencesse a IA a escrever `<img src=x onerror=...>` teria
    script rodando no navegador de quem abrisse a ocorrência, com o token do
    painel carregado ali. Dali se lê placa, telefone, endereço e conversa de
    todo mundo.

    O modelo não alcança banco nem ferramenta — ele não tem nenhuma. Este era o
    único caminho que sobrava do cliente até dado interno, e ele passava pela
    tela do operador.

    **Remover e não escapar**, porque o mesmo texto vai para dois destinos: o
    painel, que interpreta HTML, e o WhatsApp, que não. Escapar deixaria o
    cliente recebendo `&lt;b&gt;` literal no celular. E o modelo não tem motivo
    para emitir tag nenhuma: o `canal_wa_texto` já proíbe formatação.

    Mesma razão de existir do `sem_travessao`, uma linha acima: instrução de
    prompt é pedido, não garantia — e injeção de prompt existe justamente para
    transformar pedido em outra coisa.
    """
    if not texto or ("<" not in texto and "&" not in texto):
        return texto

    limpo = _TAG.sub("", texto)
    limpo = _ENTIDADE.sub("", limpo)
    # Sobrou `<` ou `>` solto (o modelo escrevendo "10 < 20"): vira texto sem
    # poder de marcação. Não dá para deixar cru — meia tag ainda abre elemento.
    limpo = limpo.replace("<", "").replace(">", "")
    return " ".join(limpo.split())


#: A saudação usada como despedida, no fim da mensagem.
#:
#: ⚠️ **Regra que o prompt pede três vezes e o modelo cumpre metade das vezes.**
#: Está na persona, está na instrução de turno, e ainda assim em 28/08/2026 saiu
#: *"Perfeito, já deixei configurado assim. Boa tarde, Bruno!"* no fim de um
#: atendimento. "Bom dia" é cumprimento de chegada; no fecho soa como quem
#: estava indo embora e lembrou de falar.
#:
#: É o tipo de regra que não se discute com o modelo: absoluta, cosmética e
#: trivial de detectar. Prompt é pedido; isto é garantia, como o travessão.
#:
#: Só corta no FIM e só quando sobra mensagem: uma resposta que é **só** "Boa
#: tarde!" é a devolução de um cumprimento dela, e essa tem de sair inteira.
_SAUDACAO_NO_FIM = re.compile(
    r"[\s]*(?:\.|,|!)?\s*"
    r"\b(?:bom\s+dia|boa\s+tarde|boa\s+noite)\b"
    r"(?:[,\s]+[A-ZÁÂÃÀÉÊÍÓÔÕÚÇ][\wÀ-ÿ]*)?"
    r"\s*[!.…]*\s*$",
    re.IGNORECASE,
)


def sem_saudacao_no_fim(texto: str) -> str:
    """Tira o "boa tarde" que fecha a mensagem. Devolve igual quando não há."""
    limpo = texto.rstrip()
    sem = _SAUDACAO_NO_FIM.sub("", limpo).rstrip()

    # Não havia saudação no fim: devolve exatamente o que veio. Sem isto a
    # função "consertaria" pontuação de mensagens que não são problema dela.
    if sem == limpo:
        return texto

    # Nada sobrou: era só o cumprimento, e cumprimento sozinho é resposta a um
    # cumprimento dela. Devolve inteiro.
    if not sem:
        return texto

    # A frase precisa terminar em alguma coisa. Cortar "…assim. Boa tarde!"
    # deixa "…assim." — mas cortar "…tudo certo Boa tarde" deixaria sem ponto.
    if sem[-1] not in ".!?…":
        sem += "."
    return sem


#: A saudação abrindo a mensagem.
#:
#: Diferente da do fim: **esta é certa na primeira fala e errada depois dela.**
#: Quem decide qual é o caso é quem tem a conversa na mão, e por isso a função
#: não adivinha nada — só corta quando mandam cortar.
_SAUDACAO_NO_INICIO = re.compile(
    r"^\s*\b(?:bom\s+dia|boa\s+tarde|boa\s+noite)\b"
    r"(?:[,\s]+[A-ZÁÂÃÀÉÊÍÓÔÕÚÇ][\wÀ-ÿ]*)?"
    r"\s*[!.,…]*\s*",
    re.IGNORECASE,
)


def sem_saudacao_no_inicio(texto: str) -> str:
    """Tira o "boa tarde" que abre a mensagem. Devolve igual quando não há."""
    sem = _SAUDACAO_NO_INICIO.sub("", texto).lstrip()
    if not sem or sem == texto.lstrip():
        return texto

    # "Boa noite, Bruno! você costuma..." → a frase que sobra precisa começar
    # com maiúscula, senão o corte fica visível.
    return sem[0].upper() + sem[1:]


#: O "Entendi, Leonardo!" que abre a resposta.
#:
#: **O problema não é a palavra, é a repetição.** Reconhecer o que a pessoa
#: acabou de dizer é boa conversa na primeira vez; na terceira seguida vira
#: tique, e tique é o que denuncia a máquina — o mesmo motivo do travessão lá
#: em cima.
#:
#: O nome entra no padrão de propósito: "Entendi, Leonardo!" é a forma que mais
#: se repete, porque o modelo tem o nome à mão e usa sempre que pode.
_ECO_DE_ABERTURA = re.compile(
    r"^\s*\b(?:entendi|entendido|certo|perfeito|beleza|ok|okay|show|legal"
    r"|bacana|combinado|tranquilo|ótimo|otimo|ótima|otima|isso\s+mesmo|isso)\b"
    r"(?:[,\s]+[A-ZÁÂÃÀÉÊÍÓÔÕÚÇ][\wÀ-ÿ]*)?"
    r"\s*[!.,…]*\s*",
    re.IGNORECASE,
)


def abre_com_reconhecimento(texto: str) -> bool:
    """A fala começa com um "entendi", "certo", "beleza"?"""
    return bool(texto and _ECO_DE_ABERTURA.match(texto))


def sem_eco_de_abertura(texto: str, anterior: str | None) -> str:
    """Corta o "entendi" de abertura **quando a fala anterior já usou um**.

    Permite uma vez, bloqueia a repetição. É como gente conversa: reconhecer o
    que o outro disse é natural; abrir toda frase do mesmo jeito é tique.

    `anterior` é a última coisa que a IA disse nesta conversa. Sem ela — na
    primeira fala — nada é cortado, porque ali o reconhecimento está certo.

    Não adivinha nada além disso: se a anterior não abriu assim, esta pode.
    """
    if anterior is None or not abre_com_reconhecimento(anterior):
        return texto
    if not abre_com_reconhecimento(texto):
        return texto

    sem = _ECO_DE_ABERTURA.sub("", texto).lstrip()
    if not sem:
        # A fala inteira era o eco. Cortar deixaria a IA muda, que é pior que
        # repetir — o silêncio, numa central, é informação errada.
        return texto
    return sem[0].upper() + sem[1:]
