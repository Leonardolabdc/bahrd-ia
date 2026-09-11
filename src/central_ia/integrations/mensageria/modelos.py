"""O texto que o cliente **já leu**, para a IA não repetir tudo de novo.

**Bug real, observado na conversa de 25/08/2026.** O template chegou no celular
do motorista dizendo evento, placa e local. Ele respondeu "Olá vou ver aqui". A
IA respondeu:

    Bom dia, Antônio! Aqui é a assistente virtual da Bahrd Monitoramento. O sistema acusou
    agora que a bateria do caminhão ABC1234 foi desligada. Beleza, fico no
    aguardo.

Três frases de preâmbulo para uma de resposta — e as três repetindo o que o
cliente tinha acabado de ler. Não foi erro de prompt: o histórico **mentia**. O
envio do template era registrado em `sessao.anotar()`, que vai para a trilha de
auditoria, e não em `sessao.historico`, que é o que o modelo lê. Do ponto de
vista do modelo, ele nunca tinha falado — e quem nunca falou se apresenta.

Este módulo devolve o corpo renderizado do modelo aprovado, com os mesmos
parâmetros que foram enviados, para virar um turno de assistente no histórico.
A partir daí a IA cumprimenta pelo nome e entra na tratativa, como faria alguém
que sabe o que já foi dito.

**Uma fonte só.** O corpo vem do `.json` que o `enviar.ps1` publica na Meta, e o
mapa nome→arquivo vem do `modelos.json` que o próprio script lê. Nada aqui
duplica texto de modelo: uma segunda cópia divergiria na primeira edição, e o
sintoma seria a IA "lembrando" de uma mensagem que o cliente não recebeu.

**Nada aqui pode derrubar um atendimento.** Arquivo faltando, JSON quebrado,
modelo desconhecido: tudo devolve `None`, e o chamador segue sem o turno — que
é exatamente o comportamento que existia antes deste módulo.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any

from central_ia.observability.logging import logger

log = logger(__name__)

#: `src/central_ia/integrations/mensageria/` → quatro níveis até a raiz, que é
#: `/app` na imagem e a pasta do repositório em desenvolvimento e nos testes. A
#: mesma expressão serve nos dois porque o `Dockerfile` copia `infra/` para o
#: lugar equivalente.
_DIRETORIO = Path(__file__).parents[4] / "infra" / "templates-whatsapp"

_MANIFESTO = "modelos.json"

#: `{{1}}`, `{{2}}` — a marcação de parâmetro da Meta.
_PARAMETRO = re.compile(r"\{\{(\d+)\}\}")

#: Cabeçalho do turno que entra no histórico.
#:
#: Diz **quatro** coisas ao modelo, e cada uma evita um erro diferente: que a
#: mensagem já foi entregue (não repita), que o cliente já a leu (não explique
#: o evento de novo), que o texto é padrão da Central e não escrito por ele
#: (não imite o "Atenciosamente" — o modelo copia o estilo do que lê, e a
#: persona é o oposto disso), e que **o cliente já foi cumprimentado**.
#:
#: ⛔ **A quarta entrou em 10/09/2026, e já tinha sido tirada daqui antes.**
#: Ela existiu em 28/08 e saiu no mesmo dia, com este argumento: *"a notificação
#: é voz do sistema, não dela — quem responde a um alerta automático não acha
#: estranho ser cumprimentado pela pessoa que aparece depois"*. Era verdade para
#: o modelo daquele dia, que abria com «🚨Notificação de Evento🚨» e assinava
#: "Central de Monitoramento".
#:
#: A premissa caiu quando o modelo passou a abrir com *"Olá, bom dia, Geraldo!
#: Tudo bem? Aqui é da Central de Monitoramento da Bahrd."* — primeira pessoa,
#: pelo nome, com saudação pela hora. **Cumprimentar de novo no turno seguinte
#: deixa de ser inofensivo e passa a denunciar que a primeira mensagem era
#: automática**, que é o oposto do que a saudação foi buscar.
#:
#: Visto numa conversa real de 10/09/2026: o cliente tocou «Preciso de ajuda!»
#: e a IA respondeu *"Bom dia, Geraldo. Sobre o alerta…"*. Bom dia duas vezes,
#: com um toque de botão no meio.
#:
#: ⚠️ **O `persona_core` já mandava não cumprimentar** — *"Cumprimente só quando
#: a sua mensagem for a primeira coisa que ela vai ler de você"*. A regra estava
#: escrita e foi violada; este cabeçalho é o lembrete no lugar onde o modelo
#: está olhando, e não vinte blocos acima.
_CABECALHO = (
    "[Notificação automática já entregue ao cliente, no modelo aprovado pela "
    "Meta. Texto padrão da Central, não escrito por você — o cliente já leu "
    "isto antes de responder. Não repita o conteúdo nem imite este tom. "
    "O cliente JÁ FOI CUMPRIMENTADO por nome nesta mensagem: não diga bom dia, "
    "boa tarde, boa noite, olá nem oi de novo — entre direto no assunto.]"
)

_AVISO_DE_MAPA = "[Junto foi o cartão de localização do WhatsApp, que abre o mapa.]"


@lru_cache(maxsize=1)
def _manifesto() -> dict[str, dict[str, Any]]:
    """Nome do modelo → entrada do manifesto. Vazio se não der para ler."""
    caminho = _DIRETORIO / _MANIFESTO
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        return {m["nome"]: m for m in dados["modelos"]}
    except Exception as erro:  # noqa: BLE001 — sem manifesto, o atendimento segue
        log.warning("manifesto_de_modelos_ilegivel", caminho=str(caminho), erro=str(erro))
        return {}


@lru_cache(maxsize=16)
def _componentes(nome: str) -> tuple[dict[str, Any], ...]:
    """Os blocos do modelo como estão publicados na Meta. Vazio se não der."""
    entrada = _manifesto().get(nome)
    if entrada is None:
        log.warning("modelo_fora_do_manifesto", modelo=nome)
        return ()

    caminho = _DIRETORIO / entrada["arquivo"]
    try:
        return tuple(json.loads(caminho.read_text(encoding="utf-8"))["components"])
    except Exception as erro:  # noqa: BLE001
        log.warning("modelo_ilegivel", modelo=nome, caminho=str(caminho), erro=str(erro))
        return ()


def _corpo_cru(nome: str) -> str | None:
    """O texto do modelo com `{{1}}` no lugar, como está publicado na Meta."""
    for componente in _componentes(nome):
        if componente.get("type") == "BODY":
            texto = componente.get("text")
            return texto if isinstance(texto, str) else None
    return None


def botoes(nome: str) -> list[str]:
    """Os rótulos dos botões que apareceram junto da mensagem.

    O operador precisa ver o que o cliente **teve para tocar**: um "não
    respondeu" muda de sentido quando se sabe que os únicos botões na tela
    levavam para a loja de aplicativos, e não para uma resposta.
    """
    for componente in _componentes(nome):
        if componente.get("type") == "BUTTONS":
            return [b["text"] for b in componente.get("buttons", []) if b.get("text")]
    return []


def corpo(nome: str, parametros: Sequence[str] | None = None) -> str | None:
    """O texto exatamente como o cliente recebeu, ou `None` se não der.

    `parametros` é a mesma lista passada ao `enviar_template` — na mesma ordem,
    porque é ela que a Meta usa para preencher `{{1}}` e `{{2}}`. Passar outra
    coisa aqui faria a IA acreditar numa mensagem que ninguém recebeu, que é
    pior do que não ter turno nenhum.
    """
    cru = _corpo_cru(nome)
    if cru is None:
        return None

    valores = list(parametros or [])

    def trocar(achado: re.Match[str]) -> str:
        indice = int(achado.group(1)) - 1
        # Fora da lista, o marcador fica como está: é mais honesto mostrar
        # `{{2}}` do que inventar um valor que o cliente não viu.
        return valores[indice] if 0 <= indice < len(valores) else achado.group(0)

    return _PARAMETRO.sub(trocar, cru)


def como_turno(
    nome: str,
    parametros: Sequence[str] | None = None,
    com_mapa: bool = False,
) -> str | None:
    """O turno de assistente pronto para entrar em `sessao.historico`."""
    texto = corpo(nome, parametros)
    if texto is None:
        return None

    partes = [_CABECALHO, "", texto]
    if com_mapa:
        partes += ["", _AVISO_DE_MAPA]
    return "\n".join(partes)
