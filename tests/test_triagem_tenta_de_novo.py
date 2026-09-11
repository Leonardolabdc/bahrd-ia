"""A triagem do pânico tenta duas vezes antes de desistir.

⚠️ **Em 02/09/2026 três pânicos de teste seguidos caíram na triagem**, cada um
por um motivo diferente, e nenhum chegou a ser classificado:

    "consumiu os 2000 tokens sem produzir conteúdo (esforço=high)"
    "Sem JSON na resposta: '```json\\n{...'"        ← cortado no meio
    "JSON inválido: confianca ... input_value='média'"

Os três são a mesma doença. O orçamento de 2000 tokens cobre **raciocínio e
resposta** — no OpenRouter os dois saem do mesmo `max_tokens` — e o esforço da
triagem é `high`. Quando o raciocínio come o teto, ou não sobra texto nenhum, ou
sobra um JSON truncado sem a chave de fechar.

⭐ **Falhar aqui é o mais caro do sistema.** A triagem decide se um pânico é
falso antes de qualquer contato. Indisponível, ela manda todo acionamento para
a fila humana: seguro, e inútil se acontece sempre.

O terceiro motivo, o acento, tem teste próprio em `test_triagem_panico_tolerante`.
"""

from __future__ import annotations

import json

import pytest

from central_ia.agent import triagem_panico
from central_ia.ports.llm import OrcamentoDeTokensEstourado, RespostaLLM, Uso

BOM = json.dumps(
    {
        "classificacao": "falso_positivo",
        "confianca": "alta",
        "probabilidade_real": 8,
        "evidencias": ["veículo parado no pátio"],
        "justificativa": "Sem deslocamento e sem histórico.",
    }
)

#: O que o Flash Lite devolveu de verdade em 02/09: cerca de código e JSON
#: cortado no meio, sem a chave de fechar.
TRUNCADO = '```json\n{\n  "classificacao": "possivel_real",\n  "confianca": "media",\n  "prob'

DADOS: dict[str, object] = {"posicao": "sem posição recente", "velocidade": "desconhecida"}


class _ClienteFalso:
    """Devolve uma resposta por chamada, na ordem, e anota o esforço pedido."""

    modelo = "falso"

    def __init__(self, *respostas: str) -> None:
        self._respostas = list(respostas)
        self.esforcos: list[str | None] = []

    async def gerar(self, *, esforco=None, **_) -> RespostaLLM:  # noqa: ANN003
        self.esforcos.append(esforco)
        return RespostaLLM(
            texto=self._respostas.pop(0),
            modelo=self.modelo,
            uso=Uso(custo_usd=0.001),
        )

    async def fechar(self) -> None:
        pass


# ──────────────────────────── a primeira já resolve ──────────────────────────


@pytest.mark.asyncio
async def test_primeira_tentativa_boa_nao_gasta_a_segunda() -> None:
    """⚠️ O caminho normal não pode ficar mais caro por causa da correção."""
    cliente = _ClienteFalso(BOM)

    triagem, custo = await triagem_panico.classificar(cliente, DADOS)

    assert triagem.probabilidade_real == 8
    assert len(cliente.esforcos) == 1, "chamou duas vezes sem precisar"
    assert custo == pytest.approx(0.001)


# ─────────────────────────── a segunda salva o caso ──────────────────────────


@pytest.mark.asyncio
async def test_json_truncado_na_primeira_e_lido_na_segunda() -> None:
    cliente = _ClienteFalso(TRUNCADO, BOM)

    triagem, custo = await triagem_panico.classificar(cliente, DADOS)

    assert triagem.classificacao == "falso_positivo"
    assert len(cliente.esforcos) == 2
    assert custo == pytest.approx(0.002), "as duas chamadas entram no custo"


@pytest.mark.asyncio
async def test_resposta_vazia_na_primeira_tambem_tem_segunda_chance() -> None:
    cliente = _ClienteFalso("", BOM)

    triagem, _ = await triagem_panico.classificar(cliente, DADOS)

    assert triagem.confianca == "alta"


@pytest.mark.asyncio
async def test_a_segunda_pensa_menos() -> None:
    """Menos raciocínio é o que sobra de orçamento para escrever.

    Repetir com o mesmo esforço repetiria a falha — foi por ele que ela veio.
    """
    cliente = _ClienteFalso(TRUNCADO, BOM)

    await triagem_panico.classificar(cliente, DADOS)

    assert cliente.esforcos[1] == triagem_panico.ESFORCO_DA_SEGUNDA_TENTATIVA
    assert cliente.esforcos[1] == "low"
    assert cliente.esforcos[0] != cliente.esforcos[1]


# ──────────────────────── e duas falhas continuam falha ──────────────────────


@pytest.mark.asyncio
async def test_duas_falhas_seguidas_ainda_vao_para_uma_pessoa() -> None:
    """⚠️ A correção não pode virar chute.

    Se as duas tentativas falharem, `TriagemInvalida` continua subindo — o
    `_triar` a trata como "caso de uma pessoa". Engolir aqui seria inventar uma
    classificação que nenhum modelo produziu, num pânico.
    """
    cliente = _ClienteFalso(TRUNCADO, "nada de json aqui")

    with pytest.raises(triagem_panico.TriagemInvalida):
        await triagem_panico.classificar(cliente, DADOS)

    assert len(cliente.esforcos) == 2, "não pode tentar uma terceira vez"


@pytest.mark.asyncio
async def test_a_cerca_de_codigo_sozinha_nao_atrapalha() -> None:
    """JSON completo dentro de ```json passa na primeira, sem segunda chamada."""
    cliente = _ClienteFalso(f"```json\n{BOM}\n```")

    triagem, _ = await triagem_panico.classificar(cliente, DADOS)

    assert triagem.probabilidade_real == 8
    assert len(cliente.esforcos) == 1


# ────────── a outra família de falha: o adaptador nem devolve texto ──────────


class _ClienteQueEstoura:
    """Primeira chamada estoura o orçamento; a segunda responde.

    ⚠️ **É o caso real de 02/09/2026 que a primeira versão desta correção
    deixou passar.** `OrcamentoDeTokensEstourado` vem do adaptador, antes de
    existir texto para parsear, então o `except TriagemInvalida` sozinho não
    pegava — e o pânico seguinte caiu igual.
    """

    modelo = "falso"

    def __init__(self) -> None:
        self.esforcos: list[str | None] = []

    async def gerar(self, *, esforco=None, **_) -> RespostaLLM:  # noqa: ANN003
        self.esforcos.append(esforco)
        if len(self.esforcos) == 1:
            raise OrcamentoDeTokensEstourado(
                "O modelo consumiu os 2000 tokens sem produzir conteúdo (esforço=high)."
            )
        return RespostaLLM(texto=BOM, modelo=self.modelo, uso=Uso(custo_usd=0.001))

    async def fechar(self) -> None:
        pass


@pytest.mark.asyncio
async def test_orcamento_estourado_na_primeira_tambem_tem_segunda_chance() -> None:
    cliente = _ClienteQueEstoura()

    triagem, custo = await triagem_panico.classificar(cliente, DADOS)

    assert triagem.probabilidade_real == 8
    assert cliente.esforcos[1] == "low"
    assert custo == pytest.approx(0.001), "a chamada que estourou não cobrou"
