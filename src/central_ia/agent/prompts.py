"""Montagem do prompt a partir dos arquivos de `prompts/`.

Quatro blocos, do mais estável ao mais volátil — a ordem não é estética, é o
que define onde o cache pode ser cortado (doc 02 §6.1):

    [1] persona_core          igual em todo atendimento
    [2] policy_guardrails     igual em todo atendimento
    [3] canal_<canal>         estável por canal
    [4] playbooks/PB-<...>    estável por playbook  ◄── breakpoint de cache

Regras que não podem ser violadas sob pena de perder o cache:

* Nada de data, hora, UUID ou nome de cliente dentro dos blocos de sistema.
* O contexto da ocorrência entra em `messages`, **nunca** em `system`.

Os arquivos são lidos uma vez e ficam em memória: relê-los a cada turno mudaria
os bytes em caso de edição no meio de uma conversa, e o cache cairia junto.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from central_ia.domain.eventos import TipoEvento

#: `prompts/` fica ao lado de `src/` no repositório e é copiado para /app.
RAIZ_PROMPTS = Path(__file__).resolve().parents[3] / "prompts"

ARQUIVO_POR_CANAL = {
    "LIGACAO": "canal_voz.md",
    "AUDIO": "canal_wa_audio.md",
    "TEXTO": "canal_wa_texto.md",
}


class PromptAusente(RuntimeError):
    """Arquivo de prompt não encontrado.

    Falha alto de propósito: um playbook faltando significaria a IA conduzindo
    um atendimento sem procedimento — pior que não atender.
    """


@lru_cache(maxsize=32)
def _ler(caminho_relativo: str) -> str:
    caminho = RAIZ_PROMPTS / caminho_relativo
    if not caminho.is_file():
        raise PromptAusente(f"Prompt não encontrado: {caminho}")
    return caminho.read_text(encoding="utf-8").strip()


def blocos_de_sistema(tipo: TipoEvento, canal: str) -> list[str]:
    """Os quatro blocos, na ordem que o cache exige."""
    if tipo.playbook is None:
        raise PromptAusente(
            f"'{tipo.rotulo}' não tem playbook — a IA não conduz este evento."
        )

    arquivo_canal = ARQUIVO_POR_CANAL.get(canal)
    if arquivo_canal is None:
        raise PromptAusente(f"Canal sem arquivo de prompt: {canal}")

    return [
        _ler("persona_core.md"),
        _ler("policy_guardrails.md"),
        _ler(arquivo_canal),
        _ler(f"playbooks/{tipo.playbook}.md"),
    ]


def versao_dos_prompts() -> str:
    """Versão gravada na trilha de auditoria junto de cada decisão.

    Enquanto não há versionamento por Git no runtime, o marcador é fixo e
    corresponde ao conjunto atual de `prompts/` (doc 03 §8).

    v2.0 acompanha a política: entrou o `PB-PANICO`, e com ele a instrução que
    manda a IA nunca dizer a palavra "pânico" na abertura.

    v2.1 saiu de uma demonstração real. O motorista disse "vou verificar" e a
    IA escalou; disse "oi, tudo bem?" e ouviu "não peguei bem sua resposta".
    Entraram a marca de espera, a distinção entre pausa e dúvida, e a regra de
    que educação vem antes do assunto.

    v2.2: o motorista que **nomeia o guincho credenciado** passa a fechar o
    caso sozinho, sem depender do gestor. A dupla confirmação continua sendo a
    regra quando o nome não bate ou o cadastro está vazio — o que mudou é que
    agora a IA tem contra o que conferir.

    ⛔ **v2.5 desfez a v2.2 por inteiro.** A verificação de guincho saiu: o
    campo do cadastro, o dado no contexto e a vigilância que observava a IA
    citando o nome antes da hora. Motivo de operação, não de código: a Central
    não valida guincho na tratativa real, então a prova conferia contra uma
    referência que ninguém mantém. No lugar entrou a pergunta de **duração da
    supressão**, que é o que o gestor pediu em 03/09/2026.

    v2.3: no `PB-PANICO`, "não sei" deixou de ser tratado como sinal de risco.
    O playbook juntava **confusão** e **perigo** na mesma caixa, e encerrava
    nos dois. Agora quem responde com naturalidade sem entender o motivo do
    contato recebe até duas perguntas neutras antes de qualquer conclusão — que
    é justamente o caso mais comum de acionamento acidental.

    v2.4: primeira leitura do fluxo da URA da Vetor. Entrou a causa que
    faltava em bateria — **base ou pátio do cliente** — e o vocabulário que o
    cliente da Bahrd já ouve há anos.

    O que **não** entrou foi a estrutura deles: menu de opções, "tecle 1", ordem
    fixa. Aquilo é desenho de sistema por regra, e copiar seria reconstruir uma
    URA cara. As cinco opções viraram lista branca, não cardápio: a IA pergunta
    aberto e classifica no que ouviu; o cliente nunca vê a lista.

    Pelo mesmo motivo o vocabulário entrou como **glossário, não como falas** —
    exemplo de frase em prompt vira roteiro recitado (foi assim que "botãozinho
    perto do banco" sobreviveu a três correções).
    """
    return "v2.5"
