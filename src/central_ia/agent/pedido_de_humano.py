"""Quando o cliente pede para falar com uma pessoa, ele vai falar com uma pessoa.

**Isto não pode depender só do modelo.** A IA já sabe escalar sozinha — ela
emite a marca quando conclui que o caso é de gente. Mas "concluir" é julgamento,
e julgamento erra: o modelo pode achar que dá conta, que a pessoa está só
desabafando, que vale mais uma pergunta antes. Em todos os outros casos essa
margem é boa e é o que faz a POC conter atendimento.

Aqui não. Pedido explícito de atendente é a única fala do cliente que **não é
matéria de opinião** — quem pede, vai. Insistir depois de um pedido desses é o
comportamento que faz as pessoas odiarem URA, e a Central existe justamente
para não parecer uma.

## Duas leituras, e por que são duas

`pediu_humano` é a **certeza**: sozinha, manda o caso para a fila humana sem
consultar o modelo.

`talvez_queira_humano` é a **suspeita**: sozinha não decide nada. Ela só vale
quando o modelo, independentemente, também concluiu que precisa escalar. Dois
sinais fracos concordando valem um forte, e nenhum dos dois manda sozinho.

Isso nasceu de uma falha real, em 27/08/2026. O cliente escreveu *"Quero falar
com algueém ai"* — com um `é` a mais. A lista tinha `falar com alguem`, a
digitação não bateu, e o caminho determinístico não disparou. **O modelo
entendeu perfeitamente** e pediu escalonamento; o caso foi fechado porque
`ESCALONAMENTO_HUMANO_ATIVO` está desligada, e o cliente ouviu "vou registrar
aqui no sistema". Duas leituras certas e um desfecho errado.

## Quem escreve isto está dirigindo

Não é conversa de escritório. O cliente digita com uma mão no volante, ou manda
áudio e o Deepgram entrega "atendende". **Exigir grafia certa de quem está no
meio de uma ocorrência é exigir a coisa errada**, e é por isso que há três
camadas de tolerância aqui, cada uma para um tipo de erro:

* `_normalizar` colapsa letra repetida — cobre `algueém`, `atendenteee`;
* `_PEDIDO` aceita até 40 caracteres entre o verbo e o substantivo — cobre
  qualquer ordem de palavras que a pessoa invente;
* `_forte_parecido` compara por semelhança — cobre troca de letra e palavra
  partida pela transcrição, que colapso nenhum resolve.

## Substantivo forte e substantivo fraco

Nem toda palavra que designa gente é pedido de gente.

**Forte** é o que ninguém diz por acaso numa conversa sobre caminhão:
"atendente", "operador", "supervisor". Aparecer já é pedido.

**Fraco** é o que aparece o tempo todo sem querer dizer nada disso: "pessoa" em
*"a pessoa que dirige o caminhão"*, "alguém" em *"alguém mexeu na bateria"*.
Estas só contam com um verbo de pedido por perto — "quero **falar com** alguém"
é pedido, "alguém mexeu" não é.

Sem essa separação, a lista transformaria conversa normal em transferência. E
transferir quem não pediu é ruim de um jeito específico: some com um
atendimento que estava indo bem, e ninguém percebe que sumiu.

## Para que lado errar

O erro é assimétrico, e é isso que decide o desenho: **deixar passar um pedido
custa mais do que transferir alguém a mais.** Quem foi transferido sem querer
fala com um operador e resolve em trinta segundos. Quem pediu e não foi
desiste — e a Central nunca fica sabendo que perdeu aquele cliente.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

_ESPACOS = re.compile(r"\s+")

#: Qualquer letra repetida em seguida: `algueém` → `algueem` → `alguem`.
_REPETIDAS = re.compile(r"(.)\1+")


def _normalizar(texto: str) -> str:
    """Minúsculo, sem acento, sem letra repetida, espaços colapsados.

    **O colapso de repetidas é o que faz a digitação parar de importar.** Em
    27/08/2026 um cliente escreveu "algueém" e o pedido dele foi ignorado: a
    lista tinha `alguem`, e substring literal não perdoa uma letra a mais.

    Colapsar resolve a classe inteira do problema em vez do caso — "algueém",
    "alguééém" e "aaatendente" chegam todos ao mesmo lugar. Custa perder a
    diferença entre `carro` e `caro`, que aqui não distingue nada, **desde que
    os dois lados da comparação passem por esta função** — inclusive os padrões
    literais deste módulo. Ver `_PEDIDO`.
    """
    sem_acento = unicodedata.normalize("NFKD", texto.lower())
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return _REPETIDAS.sub(r"\1", _ESPACOS.sub(" ", sem_acento))


#: Substantivos que, sozinhos, já são pedido de gente.
#:
#: Ninguém diz "atendente" numa conversa sobre bateria de caminhão sem estar
#: pedindo um. O mesmo não vale para "pessoa" — ver `_FRACOS`.
_FORTES: tuple[str, ...] = tuple(
    _normalizar(t)
    for t in (
        "atendente",
        "operador",
        "operadora",
        "supervisor",
        "supervisora",
        "atendimento humano",
        "ser humano",
        "de verdade",
    )
)

#: Substantivos que designam gente mas aparecem em conversa normal o tempo todo.
#: Só contam com um verbo de pedido por perto.
_FRACOS = _normalizar("pessoa|pessoas|alguem|guem|gente|humano|humana|humanos")

#: Como se pede alguma coisa, em português falado no WhatsApp.
_VERBOS = _normalizar(
    "quero|queria|gostaria|preciso|precisava|posso|pode|poderia|tem como|"
    "da para|consigo|me passa|me passe|me transfere|me transfira|transferir|"
    "transfere|chama|chamar|falar|conversar|atender"
)

#: `quero falar com alguém`, `tem como me passar para uma pessoa`.
#:
#: Até 40 caracteres entre o verbo e o substantivo cobrem "falar com **uma**",
#: "passar **para um**", "conversar **agora com**". Parar numa pontuação forte
#: é o que impede o casamento atravessar duas frases distintas.
#:
#: ⚠️ **Os dois lados passam por `_normalizar`, e é obrigatório.** `pessoa` tem
#: `ss`, que o colapso transforma em `pesoa` — o texto do cliente chegava
#: normalizado e o padrão não, e "tem como falar com uma pessoa" não batia.
#: Encontrado em 27/08/2026, no primeiro teste da lista.
_PEDIDO = re.compile(rf"\b({_VERBOS})\b[^.!?;]{{0,40}}\b({_FRACOS})\b")

#: Recusar a máquina é pedir gente, dito ao contrário.
_RECUSAS: tuple[str, ...] = tuple(
    _normalizar(t)
    for t in (
        "nao quero falar com robo",
        "nao quero falar com maquina",
        "nao quero falar com bot",
        "nao quero falar com ia",
        "nao quero robo",
        "cansei do robo",
        "isso e um robo",
        "voce e um robo",
        "e um robo",
        "falando com robo",
        "sair do robo",
        "odeio robo",
    )
)

#: Pedir a Central por outro canal também é pedir gente.
_OUTRO_CANAL: tuple[str, ...] = tuple(
    _normalizar(t)
    for t in (
        "me liga",
        "pode me ligar",
        "quero ligar",
        "prefiro por telefone",
        "falar por telefone",
        "numero para ligar",
    )
)

#: Só para a suspeita: qualquer palavra que designe gente, sem exigir verbo.
#:
#: Permissiva de propósito — ela nunca decide sozinha. Ver `talvez_queira_humano`.
_QUALQUER_HUMANO = re.compile(rf"\b({_FRACOS}|atendente|operador|supervisor|robo|bot)\b")

#: Palavras cuja **semelhança** já basta, sem precisar da grafia certa.
#:
#: Só substantivos fortes entram aqui. Os fracos ficam de fora de propósito:
#: `alguem` e `algum` são 90% parecidos, e "tem algum problema" viraria pedido
#: de atendente. Palavra fraca continua exigindo verbo de pedido por perto, que
#: é uma trava melhor do que qualquer limiar.
_FORTES_APROXIMAVEIS: tuple[str, ...] = (
    "atendente",
    "operador",
    "supervisor",
    "humano",
)

#: Quão parecido basta. Calibrado nos dois lados:
#:
#:   atendente ~ atendete    0.94 ✓  digitação com uma mão
#:   atendente ~ atendende   0.89 ✓  áudio mal transcrito
#:   atendente ~ atender     0.75 ✗  verbo comum, fica de fora
#:
#: Baixar isto começa a pegar `atender`, que aparece em conversa normal.
_SEMELHANCA = 0.82

#: Palavra curta demais colide por acaso — `humano` tem 6 letras e é o menor
#: alvo. Abaixo disso, duas letras diferentes já são um terço da palavra.
_TAMANHO_MINIMO = 5

_PALAVRA = re.compile(r"[a-z]+")


def _forte_parecido(normalizado: str) -> str | None:
    """Um substantivo forte escrito errado, ou `None`.

    Compara palavra a palavra, e não a frase inteira, porque transcrição ruim
    também **parte** palavra: "a tendente" vira dois tokens, e `tendente`
    sozinho ainda se parece com `atendente`.
    """
    for palavra in _PALAVRA.findall(normalizado):
        if len(palavra) < _TAMANHO_MINIMO:
            continue
        for alvo in _FORTES_APROXIMAVEIS:
            if SequenceMatcher(None, palavra, alvo).ratio() >= _SEMELHANCA:
                return palavra
    return None


def pediu_humano(texto: str) -> str | None:
    """A expressão que bateu, ou `None`. **Sozinha, manda para a fila humana.**

    Devolve **qual** expressão, e não só `True`, porque isso vai para a trilha
    da ocorrência. O operador que recebe o caso abre a conversa sabendo que o
    cliente pediu por ele, e com que palavras — e quem for ajustar as listas
    depois consegue ver, caso a caso, o que estava disparando e o que não.
    """
    normalizado = _normalizar(texto)

    for grupo in (_FORTES, _RECUSAS, _OUTRO_CANAL):
        achado = next((t for t in grupo if t in normalizado), None)
        if achado is not None:
            return achado

    pedido = _PEDIDO.search(normalizado)
    if pedido is not None:
        return pedido.group(0)

    # Por último, e só por último: a grafia errada. Deixar por último faz a
    # trilha mostrar a expressão exata sempre que ela existir, e a aproximada
    # só quando não havia outra.
    return _forte_parecido(normalizado)


def talvez_queira_humano(texto: str) -> bool:
    """Suspeita, não certeza. **Não decide nada sozinha.**

    Permissiva de propósito: basta uma palavra que designe gente, sem exigir
    verbo de pedido. Sozinha ela erraria muito — "alguém mexeu na bateria"
    passa.

    Ela só é consultada quando o **modelo**, por conta própria, já concluiu que
    o caso precisa escalar. Aí a pergunta deixa de ser "o cliente pediu?" e
    passa a ser "o que ele falou tem a ver com gente?" — e dois sinais fracos
    concordando valem um forte.
    """
    normalizado = _normalizar(texto)
    return bool(_QUALQUER_HUMANO.search(normalizado)) or _forte_parecido(normalizado) is not None
