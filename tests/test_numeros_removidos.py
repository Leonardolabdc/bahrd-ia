"""Quem pediu para sair, sai. E o alarme dos outros continua saindo.

⛔ **Não é conveniência, é obrigação de plataforma.** Uma linha de celular
cancelada é reciclada pela operadora, e o cadastro da Bahrd continua apontando
para ela: quem atende passa a receber alarme de um caminhão que nunca foi seu.
Continuar mandando depois do pedido derruba a nota de qualidade do número na
Meta e, no limite, tira a conta do ar — e aí **nenhum** cliente recebe nada.

⚠️ **O erro simétrico é pior que o erro que este módulo evita.** Bloquear quem
não pediu significa alerta de roubo que não chega em ninguém. Por isso o
bloqueio é por (número, placa) e não pelo número inteiro, a IA confirma antes,
e o Redis fora do ar deixa a mensagem passar em vez de calar o alarme.
"""

from __future__ import annotations

import json

import pytest

from central_ia.api.rotas import whatsapp as rota
from central_ia.config import Settings
from central_ia.domain import eventos as catalogo
from central_ia.orchestration import numeros_removidos


class _RedisFalso:
    """Um hash na memória, com a mesma superfície que o módulo usa."""

    def __init__(self) -> None:
        self.dados: dict[str, str] = {}

    async def hset(self, _chave: str, campo: str, valor: str) -> int:
        self.dados[campo] = valor
        return 1

    async def hexists(self, _chave: str, campo: str) -> bool:
        return campo in self.dados

    async def hgetall(self, _chave: str) -> dict[str, str]:
        return dict(self.dados)

    async def hdel(self, _chave: str, campo: str) -> int:
        return 1 if self.dados.pop(campo, None) is not None else 0


class _RedisMorto:
    """Tudo estoura. É o Redis fora do ar."""

    async def hexists(self, *_a: object) -> bool:
        raise ConnectionError("redis fora")

    async def hgetall(self, *_a: object) -> dict[str, str]:
        raise ConnectionError("redis fora")


@pytest.fixture
def redis(monkeypatch) -> _RedisFalso:
    falso = _RedisFalso()
    monkeypatch.setattr(numeros_removidos.redis_bus, "cliente", lambda _cfg: falso)
    return falso


def _cfg() -> Settings:
    return Settings()


class TestOEscopoEOPar:
    """Por (número, placa). A escolha e o preço dela."""

    @pytest.mark.asyncio
    async def test_bloqueia_a_placa_pedida(self, redis) -> None:
        await numeros_removidos.remover(
            _cfg(), "+5541999990001", "AAA1111", ocorrencia_id="OC-1", pedido="nao e meu"
        )

        assert await numeros_removidos.esta_removido(_cfg(), "+5541999990001", "AAA1111")

    @pytest.mark.asyncio
    async def test_nao_bloqueia_as_outras_placas_do_mesmo_numero(self, redis) -> None:
        """⚠️ **É o preço da decisão de 10/09/2026, e está aqui para não surpreender.**

        Bloquear o número inteiro resolveria a linha reciclada de uma vez. Por
        placa, se o cadastro antigo tinha cinco caminhões, a pessoa errada
        precisa pedir cinco vezes.

        O que se compra com isso: um engano de leitura da IA tira o contato de
        **um** veículo, e não de toda a frota de quem estava certo.
        """
        await numeros_removidos.remover(
            _cfg(), "+5541999990001", "AAA1111", ocorrencia_id="OC-1", pedido="x"
        )

        assert not await numeros_removidos.esta_removido(_cfg(), "+5541999990001", "BBB2222")

    @pytest.mark.asyncio
    async def test_nao_bloqueia_a_mesma_placa_de_outro_numero(self, redis) -> None:
        """O dono de verdade continua sendo avisado do próprio caminhão."""
        await numeros_removidos.remover(
            _cfg(), "+5541999990001", "AAA1111", ocorrencia_id="OC-1", pedido="x"
        )

        assert not await numeros_removidos.esta_removido(_cfg(), "+5541988887777", "AAA1111")


class TestAsGrafiasDoMesmoCelular:
    """⛔ A normalização é o que faz o bloqueio funcionar de verdade.

    O mesmo celular chega como `+5541999999999` pelo payload da Bahrd,
    `554199999999` pelo webhook da Meta e `whatsapp:+55...` pelo Twilio.
    Comparar texto puro bloquearia numa grafia e deixaria passar nas outras — e
    o sintoma seria a pessoa recebendo de novo depois de ter pedido para parar,
    que é exatamente o que este módulo existe para impedir.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "grafia",
        ["+5541999990001", "5541999990001", "whatsapp:+5541999990001", "554199990001"],
    )
    async def test_qualquer_grafia_encontra_o_bloqueio(self, redis, grafia: str) -> None:
        await numeros_removidos.remover(
            _cfg(), "+5541999990001", "AAA1111", ocorrencia_id="OC-1", pedido="x"
        )

        assert await numeros_removidos.esta_removido(_cfg(), grafia, "AAA1111")

    @pytest.mark.asyncio
    async def test_a_placa_ignora_caixa_e_espaco(self, redis) -> None:
        await numeros_removidos.remover(
            _cfg(), "+5541999990001", "aaa1111", ocorrencia_id="OC-1", pedido="x"
        )

        assert await numeros_removidos.esta_removido(_cfg(), "+5541999990001", " AAA1111 ")


class TestQuandoOArmazenamentoFalha:
    """A indisponibilidade não pode calar o alarme."""

    @pytest.mark.asyncio
    async def test_redis_fora_deixa_a_mensagem_passar(self, monkeypatch) -> None:
        """⛔ Das duas saídas ruins, esta é a menos ruim.

        Ou mandamos para quem pediu para não receber, ou não mandamos para
        ninguém. A segunda é pior: um alarme de roubo que não sai é o que este
        sistema existe para evitar. A falha fica no log para a investigação.
        """
        monkeypatch.setattr(numeros_removidos.redis_bus, "cliente", lambda _cfg: _RedisMorto())

        assert not await numeros_removidos.esta_removido(_cfg(), "+5541999990001", "AAA1111")

    @pytest.mark.asyncio
    async def test_registro_torto_nao_derruba_a_aba(self, redis) -> None:
        """Um JSON quebrado some sozinho; os outros continuam na lista."""
        redis.dados["lixo"] = "{isto nao e json"
        await numeros_removidos.remover(
            _cfg(), "+5541999990001", "AAA1111", ocorrencia_id="OC-1", pedido="x"
        )

        lista = await numeros_removidos.listar(_cfg())

        assert [i.placa for i in lista] == ["AAA1111"]


class TestDesfazer:
    """⛔ Existe porque a IA pode errar, e quem percebe não tem acesso ao Redis."""

    @pytest.mark.asyncio
    async def test_devolve_o_numero_aos_avisos(self, redis) -> None:
        await numeros_removidos.remover(
            _cfg(), "+5541999990001", "AAA1111", ocorrencia_id="OC-1", pedido="x"
        )

        assert await numeros_removidos.devolver(_cfg(), "+5541999990001", "AAA1111") is True
        assert not await numeros_removidos.esta_removido(_cfg(), "+5541999990001", "AAA1111")

    @pytest.mark.asyncio
    async def test_devolver_o_que_nao_estava_bloqueado_e_inofensivo(self, redis) -> None:
        assert await numeros_removidos.devolver(_cfg(), "+5541999990001", "AAA1111") is False


class TestOQueOOperadorLe:
    """A lista precisa carregar o que faz o operador julgar e agir."""

    @pytest.mark.asyncio
    async def test_guarda_a_frase_do_cliente(self, redis) -> None:
        """Sem ela, o operador não distingue pedido de engano de leitura da IA."""
        await numeros_removidos.remover(
            _cfg(),
            "+5541999990001",
            "AAA1111",
            ocorrencia_id="OC-2026-09-10-XXXX-WA",
            pedido="esse numero era de outra pessoa, nao tenho caminhao",
        )

        (item,) = await numeros_removidos.listar(_cfg())

        assert "outra pessoa" in item.pedido
        assert item.ocorrencia_id == "OC-2026-09-10-XXXX-WA"

    @pytest.mark.asyncio
    async def test_a_frase_longa_e_cortada(self, redis) -> None:
        """Texto do cliente é entrada não confiável; 300 caracteres bastam."""
        await numeros_removidos.remover(
            _cfg(), "+5541999990001", "AAA1111", ocorrencia_id="OC-1", pedido="a" * 5000
        )

        guardado = json.loads(next(iter(redis.dados.values())))

        assert len(guardado["pedido"]) == 300


class TestAPalavraChaveDoRodape:
    """`REMOVER` é atalho determinístico, e precisa não disparar sozinho."""

    @pytest.mark.parametrize("corpo", ["REMOVER", "remover", "  Remover  ", "REMOVER.", "remover!"])
    def test_a_palavra_sozinha_dispara(self, corpo: str) -> None:
        assert rota._pediu_remocao(corpo)

    @pytest.mark.parametrize(
        "corpo",
        [
            # ⛔ O caso que faria a IA perguntar se a pessoa quer parar de
            # receber alarme do próprio caminhão no meio de um atendimento.
            "nao vou remover a bateria agora",
            "o mecanico vai remover amanha",
            "remover o que?",
            "",
        ],
    )
    def test_a_palavra_no_meio_da_frase_nao_dispara(self, corpo: str) -> None:
        assert not rota._pediu_remocao(corpo)


def test_os_tres_eventos_que_notificam_aceitam_o_desfecho() -> None:
    """A linha errada recebe os três, então os três precisam saber sair.

    ⚠️ Não é desfecho do alarme: o evento continua sem causa apurada, e o
    veículo segue disparando para quem mais estiver no cadastro. É desfecho do
    **contato**.
    """
    for codigo in ("REMOCAO_BATERIA", "MOVIMENTO_SEM_IGNICAO", "PANICO"):
        assert catalogo.desfecho_permitido(codigo, rota.DESFECHO_REMOCAO), codigo
