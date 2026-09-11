"""O turno que quebrou a conversa em 28/08/2026, e o que impede que quebre de novo.

⚠️ **Falha real, achada rodando os roteiros do doc 23.** No roteiro A3 o cliente
recusa a supressão dos avisos, que é a decisão mais difícil do playbook de
bateria. O modelo consumiu os 400 tokens de saída **raciocinando** e devolveu
conteúdo vazio.

No OpenRouter os tokens de raciocínio saem do mesmo orçamento da resposta, e
`finish_reason` volta `length` com `content` vazio. O adaptador já detectava
isso e levantava erro, o que estava certo; o que não estava era o resto:

* o teto de 400 era apertado demais para um turno difícil;
* qualquer erro virava `falha_tecnica_no_atendimento`, e o cliente recebia
  *"vou registrar aqui no sistema"* para um caso que **não** foi registrado.

O conserto tem duas partes, e as duas são testadas aqui: teto maior, e uma
segunda tentativa com menos raciocínio. Pedir menos raciocínio é o que de fato
fecha o buraco, porque raciocínio se expande até onde couber.
"""

from __future__ import annotations

import pytest

from central_ia.agent import atendimento_real
from central_ia.domain import eventos as catalogo
from central_ia.ports.llm import (
    Mensagem,
    OrcamentoDeTokensEstourado,
    RespostaLLM,
    RespostaVaziaDoModelo,
    Uso,
)

TIPO = catalogo.por_codigo("REMOCAO_BATERIA")
HISTORICO = [
    Mensagem(papel="user", conteudo="não, prefiro continuar recebendo os avisos"),
]


class LLMQueEstoura:
    """Estoura o orçamento nas `n` primeiras chamadas e responde depois."""

    modelo = "dublê"

    def __init__(self, estouros: int) -> None:
        self.restam = estouros
        self.esforcos: list[str | None] = []
        self.tetos: list[int] = []

    async def gerar(self, *, blocos_sistema, mensagens, max_tokens, esforco=None, **_):  # noqa: ARG002
        self.esforcos.append(esforco)
        self.tetos.append(max_tokens)
        if self.restam > 0:
            self.restam -= 1
            raise OrcamentoDeTokensEstourado(
                f"O modelo consumiu os {max_tokens} tokens sem produzir conteúdo "
                f"(esforço={esforco})."
            )
        return RespostaLLM(
            texto="Sem problema, Bruno. Vou manter os avisos ligados então.",
            modelo=self.modelo,
            motivo_parada="end_turn",
            uso=Uso(tokens_entrada=10, tokens_saida=20, custo_usd=0.001),
        )

    async def fechar(self) -> None:
        pass


@pytest.mark.asyncio
async def test_o_turno_tenta_de_novo_com_menos_raciocinio() -> None:
    """A conversa continua. É o teste que a falha de 28/08 não teria passado."""
    llm = LLMQueEstoura(estouros=1)

    turno = await atendimento_real.proximo_turno(llm, TIPO, "TEXTO", HISTORICO)

    assert turno.mensagem, "a segunda tentativa tem de produzir fala"
    assert len(llm.esforcos) == 2, "tentou uma vez, e uma vez só"
    assert llm.esforcos[1] == atendimento_real.ESFORCO_DA_SEGUNDA_TENTATIVA
    assert llm.esforcos[1] != llm.esforcos[0], "de nada adianta repetir igual"


@pytest.mark.asyncio
async def test_a_segunda_tentativa_e_uma_so() -> None:
    """Se ela também estourar, o caso é de humano.

    Insistir seria trocar um silêncio por um silêncio mais caro: a pessoa está
    esperando, e cada tentativa custa segundos que ela vê passar. Quem trata a
    exceção que sobe daqui é o `_falar`, virando escalonamento.
    """
    llm = LLMQueEstoura(estouros=5)

    with pytest.raises(OrcamentoDeTokensEstourado):
        await atendimento_real.proximo_turno(llm, TIPO, "TEXTO", HISTORICO)

    assert len(llm.esforcos) == 2, "duas chamadas no total, nunca uma terceira"


@pytest.mark.asyncio
async def test_o_teto_de_tokens_cabe_o_raciocinio_e_a_fala() -> None:
    """400 não cabia. O número novo tem de ter folga sobre o teto da fala.

    A `blindagem` corta a mensagem da IA em 700 caracteres, uns 180 tokens. O
    que sobra é o espaço de raciocínio, e é ele que faltava.
    """
    from central_ia.agent import blindagem

    llm = LLMQueEstoura(estouros=0)
    await atendimento_real.proximo_turno(llm, TIPO, "TEXTO", HISTORICO)

    tokens_da_fala = blindagem.LIMITE_SAIDA // 4
    assert llm.tetos[0] == atendimento_real.MAX_TOKENS_DO_TURNO
    assert atendimento_real.MAX_TOKENS_DO_TURNO >= tokens_da_fala * 3, (
        "sem folga para o raciocínio, o turno difícil volta a devolver vazio"
    )


def test_o_estouro_tem_excecao_propria() -> None:
    """Genérico demais seria pior do que nada.

    Se o estouro chegasse como `RuntimeError`, a segunda tentativa também
    pegaria chave inválida e provedor fora do ar, que não melhoram repetindo.
    Repetir esses dois só faz a pessoa esperar o dobro pelo mesmo silêncio.
    """
    assert issubclass(OrcamentoDeTokensEstourado, RuntimeError)
    assert issubclass(RespostaVaziaDoModelo, RuntimeError)

    import inspect

    fonte = inspect.getsource(atendimento_real.proximo_turno)
    assert "except (OrcamentoDeTokensEstourado, RespostaVaziaDoModelo)" in fonte
    assert "except RuntimeError" not in fonte
    assert "except Exception" not in fonte


def test_vazio_com_parada_stop_tambem_e_repetido() -> None:
    """⚠️ **O buraco a dois passos da rede, fechado em 02/09/2026.**

    A segunda tentativa existia desde 28/08 e só pegava
    `OrcamentoDeTokensEstourado`, que o adaptador levanta apenas quando o
    `finish_reason` é `length`. Num pânico real o modelo devolveu vazio dizendo
    `stop`: o adaptador deixava passar, o erro só aparecia depois do parse como
    `TurnoVazio`, e aí já estava fora do alcance do retry. O cliente tocou em
    «Preciso de ajuda!» e o caso foi para a fila humana sem uma palavra.

    As duas se resolvem igual, pedindo menos raciocínio. Continuam separadas
    porque só a primeira também se resolveria aumentando o orçamento.
    """
    import inspect

    from central_ia.integrations.llm import openrouter

    fonte = inspect.getsource(openrouter.ClienteOpenRouter.gerar)
    assert "raise RespostaVaziaDoModelo" in fonte, "vazio com `stop` precisa levantar"
    assert 'finish_reason") == "length"' in fonte, "o estouro continua tendo causa própria"
