"""Triagem prévia dos eventos críticos — antes de a IA falar com alguém.

Política v2.0. A IA trata todo tipo de evento, inclusive pânico. O que a
protege não é mais o *tipo* do evento, é a *evidência*: neste módulo ela cruza
telemetria, rota e histórico do equipamento e devolve **quanto o caso parece
ser real**, de 0 a 100.

    probabilidade_real ≥ LIMIAR_ESCALONAMENTO  →  humano, sem contato nenhum
    probabilidade_real <  LIMIAR_ESCALONAMENTO →  a IA conduz o atendimento

O prompt é conservador em uma direção só, e continua sendo. Superestimar um
alarme falso custa o tempo de um operador; subestimar um caso real custa o
atendimento de alguém num assalto. Por isso a instrução manda **arredondar
para cima** diante de qualquer ruído.

A saída é JSON validado por Pydantic. Se vier malformada, a triagem falha e o
caso vai para o humano — falha nunca vira classificação, e nunca vira contato.
"""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any, Literal

import structlog
from pydantic import BaseModel, Field, ValidationError, field_validator

from central_ia.agent.esforco import esforco_da_triagem
from central_ia.domain.eventos import LIMIAR_ENCERRAMENTO_AUTONOMO, LIMIAR_ESCALONAMENTO
from central_ia.observability.tracing import Turno
from central_ia.ports.llm import (
    ClienteLLM,
    Esforco,
    Mensagem,
    OrcamentoDeTokensEstourado,
    RespostaLLM,
    RespostaVaziaDoModelo,
)

log = structlog.get_logger(__name__)

Classificacao = Literal["falso_positivo", "inconclusivo", "possivel_real"]
Confianca = Literal["baixa", "media", "alta"]


def _sem_acento(valor: Any) -> Any:
    """`"Média"` → `"media"`. Só mexe em texto; o resto passa intacto.

    ⚠️ **Um acento derrubou a triagem de um pânico real em 02/09/2026.** O
    modelo respondeu `"confianca": "média"` e o Pydantic recusou, porque o
    `Literal` é `"media"`. A triagem virou `TriagemInvalida`, e o caminho de
    falha fez o que devia: nenhum contato, caso para uma pessoa. Só que nesta
    fase da POC não há pessoa, e o evento foi encerrado sem ninguém falar com
    o cliente.

    **A palavra estava certa e a intenção era inequívoca.** Recusar `"média"`
    não protegia de nada — não é ambiguidade, é ortografia. Rigor que só
    aparece como indisponibilidade não é rigor, é fragilidade.

    O conjunto de valores aceitos **não mudou**: continuam sendo três. O que
    mudou é parar de recusar o mesmo valor escrito com acento ou em caixa alta.
    Vale para qualquer modelo — o Sonnet acerta mais, não sempre.
    """
    if not isinstance(valor, str):
        return valor
    sem = unicodedata.normalize("NFKD", valor.strip().lower())
    return "".join(c for c in sem if not unicodedata.combining(c))


class Triagem(BaseModel):
    classificacao: Classificacao
    confianca: Confianca
    probabilidade_real: int = Field(
        ge=0,
        le=100,
        description="Quanto o caso parece ser real, de 0 a 100. É este número, "
        "e não a classificação, que decide se o humano assume.",
    )
    evidencias: list[str] = Field(
        description="Fatos observados nos dados, um por item. Sem interpretação."
    )
    justificativa: str = Field(description="Duas ou três frases ligando as evidências.")

    @field_validator("classificacao", "confianca", mode="before")
    @classmethod
    def _tolera_acento_e_caixa(cls, valor: Any) -> Any:
        return _sem_acento(valor)

    @property
    def exige_humano(self) -> bool:
        return self.probabilidade_real >= LIMIAR_ESCALONAMENTO

    @property
    def pode_encerrar_sozinha(self) -> bool:
        """Autoriza o fechamento automático — e exige as três coisas juntas.

        Probabilidade baixa sozinha não basta: 15% com confiança baixa quer
        dizer "não sei", não "é falso". Por isso a classificação e a confiança
        entram na conta. Uma condição a menos aqui é um caso real fechado sem
        ninguém olhar.
        """
        return (
            self.probabilidade_real <= LIMIAR_ENCERRAMENTO_AUTONOMO
            and self.confianca == "alta"
            and self.classificacao == "falso_positivo"
        )

    @property
    def faixa(self) -> str:
        """Como a decisão aparece na trilha de auditoria e no painel."""
        if self.exige_humano:
            return "humano_assume"
        if self.pode_encerrar_sozinha:
            return "ia_encerra"
        return "ia_atende_operador_revisa"


INSTRUCAO = f"""\
Você apoia a triagem de uma central de monitoramento de frotas no Brasil.

Recebe um alerta CRÍTICO (pânico ou veículo com roubo ativo) e os dados do
sistema interno sobre o veículo, a rota e o histórico do equipamento. Sua
tarefa é estimar **quanto este caso parece ser real**.

Esta estimativa decide o que acontece em seguida:

- {LIMIAR_ESCALONAMENTO} ou mais: um operador humano assume imediatamente e
  ninguém entra em contato automático.
- entre {LIMIAR_ENCERRAMENTO_AUTONOMO} e {LIMIAR_ESCALONAMENTO}: um agente
  automático fala com o motorista, e um operador revisa o fechamento depois.
- {LIMIAR_ENCERRAMENTO_AUTONOMO} ou menos, **com confiança alta**: o agente
  fala com o motorista e pode encerrar o caso sozinho, sem nenhum operador
  olhar. Use esta faixa apenas quando todos os sinais apontarem juntos para
  alarme falso e não houver nada em aberto.

Sinais que EMPURRAM PARA CIMA (mais provável ser real): desvio de rota, parada
não prevista, acostamento, velocidade incompatível com o trecho, evento
correlato na janela (jammer, movimento sem ignição, remoção de bateria),
veículo já marcado como roubado, carga de alto valor, ausência de histórico de
acionamento acidental.

Sinais que EMPURRAM PARA BAIXO (mais provável ser alarme falso): veículo
seguindo a rota prevista em velocidade normal, nenhum evento correlato na
janela, e — o mais forte de todos — histórico de acionamentos anteriores que o
**operador confirmou** como acidentais.

Regra de arredondamento: diante de dado ausente, sinal que não fecha ou
qualquer ruído, **arredonde para cima**. Um alarme falso mandado para o humano
custa o tempo de um operador. Um caso real mandado para o agente automático
custa o atendimento de uma pessoa. Os dois erros não têm o mesmo preço.

Se o veículo já estiver marcado como roubado, a probabilidade nunca é menor
que {LIMIAR_ESCALONAMENTO}.

Em `evidencias`, escreva apenas fatos que estão nos dados, um por item, sem
interpretar. A interpretação vai em `justificativa`.

`classificacao` acompanha o número: `falso_positivo` quando tudo aponta junto
para alarme falso, `possivel_real` quando há indício de ocorrência real,
`inconclusivo` no meio.

Responda SOMENTE com JSON, sem cercas de código, neste formato:
{{"classificacao": "...", "confianca": "...", "probabilidade_real": 0,
"evidencias": ["..."], "justificativa": "..."}}\
"""

_JSON = re.compile(r"\{.*\}", re.DOTALL)


class TriagemInvalida(RuntimeError):
    """A saída do modelo não pôde ser lida. O caso vai para o humano."""


def _dados_como_texto(dados: dict[str, object]) -> str:
    return "\n".join(f"- {chave}: {valor}" for chave, valor in dados.items())


#: Esforço da segunda tentativa. Baixo pelo mesmo motivo do `atendimento_real`:
#: ela não existe para pensar melhor, existe para **responder**.
ESFORCO_DA_SEGUNDA_TENTATIVA: Esforco = "low"


def _ler(texto: str) -> Triagem:
    """O JSON de dentro do texto, ou `TriagemInvalida` dizendo o que veio."""
    achado = _JSON.search(texto or "")
    if not achado:
        raise TriagemInvalida(f"Sem JSON na resposta: {(texto or '')[:200]!r}")
    try:
        return Triagem.model_validate(json.loads(achado.group()))
    except (json.JSONDecodeError, ValidationError) as erro:
        raise TriagemInvalida(f"JSON inválido: {erro}") from erro


async def classificar(
    cliente: ClienteLLM,
    dados: dict[str, object],
    observado: Turno | None = None,
) -> tuple[Triagem, float]:
    """Devolve `(triagem, custo_usd)`. Levanta `TriagemInvalida` se não der para ler.

    `observado` é o anotador do span, e vem de fora de propósito: quem tem o
    contexto da ocorrência é o `_triar`, quem tem os tokens e o modelo é esta
    função. Passar o anotador em vez de criar o span aqui mantém a divisão, e
    deixa a triagem cair na **mesma sessão** do Langfuse que os turnos depois.

    ⚠️ Registra as **duas** tentativas quando a primeira falha, cada uma com o
    seu custo. Registrar só a que deu certo esconderia exatamente o caso que a
    gente quer investigar: o pânico que gastou duas chamadas para responder.

    ⚠️ **Tenta duas vezes, e a segunda pensa menos de propósito.**
    Em 02/09/2026 três pânicos de teste seguidos caíram aqui, cada um por um
    motivo diferente:

        "consumiu os 2000 tokens sem produzir conteúdo (esforço=high)"
        "Sem JSON na resposta: '```json\\n{...'"   ← cortado no meio
        "JSON inválido: confianca ... input_value='média'"

    Os três são a mesma doença. O orçamento cobre **raciocínio e resposta**: no
    OpenRouter os dois saem do mesmo `max_tokens`, e `esforco_da_triagem()` é
    `high`. Quando o raciocínio come o teto, ou não sobra texto, ou sobra um
    JSON truncado sem a chave de fechar.

    ⭐ **E o custo de falhar aqui é o mais alto do sistema.** A triagem é o que
    decide se um pânico é falso antes de qualquer contato. Ela indisponível
    manda todo acionamento para a fila humana — o comportamento seguro, e
    inútil se acontece sempre.

    A segunda tentativa é o mesmo remédio que o `atendimento_real` já usava:
    menos raciocínio, mais orçamento para escrever. Custa uma chamada a mais
    **só quando a primeira falha**, e é a chamada mais barata de repetir do
    projeto — uma vez por ocorrência, não uma por turno.
    """
    # ⚠️ **As duas famílias de falha, e por que estão no mesmo `try`.**
    #
    # `OrcamentoDeTokensEstourado` vem do adaptador, quando o raciocínio comeu o
    # teto e não sobrou texto nenhum. `TriagemInvalida` vem daqui, quando sobrou
    # texto mas ele está truncado ou malformado. São o mesmo problema em dois
    # estágios — a primeira versão desta correção só pegava a segunda, e o teste
    # real seguinte caiu na primeira, em 02/09/2026.
    custo = 0.0
    try:
        resposta = await cliente.gerar(
            blocos_sistema=[INSTRUCAO],
            mensagens=[Mensagem(papel="user", conteudo=_dados_como_texto(dados))],
            max_tokens=2000,
            esforco=esforco_da_triagem(),
        )
        custo = resposta.uso.custo_usd or 0.0
        _anotar(observado, resposta, tentativa=1)
        return _ler(resposta.texto or ""), custo
    except (TriagemInvalida, OrcamentoDeTokensEstourado, RespostaVaziaDoModelo) as erro:
        log.warning("triagem_ilegivel_tentando_com_menos_esforco", erro=str(erro))

    # Sem `try` aqui: se a segunda também não deu, o caso é de uma pessoa, e o
    # `_triar` trata as duas exceções como isso. Engolir seria inventar uma
    # classificação que ninguém produziu, num pânico.
    segunda = await cliente.gerar(
        blocos_sistema=[INSTRUCAO],
        mensagens=[Mensagem(papel="user", conteudo=_dados_como_texto(dados))],
        max_tokens=2000,
        esforco=ESFORCO_DA_SEGUNDA_TENTATIVA,
    )
    custo += segunda.uso.custo_usd or 0.0
    _anotar(observado, segunda, tentativa=2)
    return _ler(segunda.texto or ""), custo


def _anotar(observado: Turno | None, resposta: RespostaLLM, *, tentativa: int) -> None:
    """Manda para o span o que a chamada gastou, se houver span.

    `modelo` sai de `resposta.modelo`, que é o que o provedor **devolveu**, não o
    que pedimos: se a OpenRouter rotear para outro, é o real que aparece no
    Langfuse. É o mesmo campo que o `atendimento_real` usa, pela mesma razão.
    """
    if observado is None:
        return
    observado.registrar(
        modelo=resposta.modelo,
        tokens_entrada=resposta.uso.tokens_entrada,
        tokens_saida=resposta.uso.tokens_saida,
        tokens_cache=resposta.uso.tokens_cache_leitura,
        custo_usd=resposta.uso.custo_usd,
        # A tentativa vira metadado porque a segunda só existe quando a primeira
        # falhou: filtrar por ela no Langfuse é a forma de medir com que
        # frequência a triagem precisa de duas chamadas.
        versao_prompt=f"triagem.tentativa-{tentativa}",
        saida=resposta.texto,
    )
