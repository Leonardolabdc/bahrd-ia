"""O que a conversa decidiu que precisa ser feito no sistema da Bahrd.

A IA conversa, entende a causa e chega a uma decisão: *inativar os eventos deste
caminhão enquanto ele estiver na oficina*. Alguém precisa executar isso no
sistema da Bahrd — e esse alguém ainda não existe, porque a API de escrita
depende da TI deles.

Este módulo é a resposta a isso, e ele não é um remendo de espera. **A decisão e
a execução são coisas separadas mesmo quando as duas existem.** Guardar a
decisão dá auditoria, permite reexecutar o que falhou, e deixa o operador ver o
que a IA combinou com o cliente antes de qualquer sistema ser tocado.

Hoje o executor só registra. No dia em que a API existir, ele executa — e nada
mais muda, porque o resto do código nunca conheceu a API.

## A regra que governa isto

**A IA propõe, o código valida contra lista branca, o código executa.** É a
regra combinada com a TI da Bahrd, e `Acao` é ela em forma de tipo: um conjunto **fechado** de
operações nomeadas. Não existe "executar comando", não existe parâmetro que
vira SQL, não existe nome de tabela vindo de texto.

Isso importa mais aqui do que em qualquer outro lugar do projeto: é o único
ponto em que uma conversa com um cliente chega perto de escrever no banco da
empresa. Uma injeção bem-sucedida em qualquer outro lugar faz a IA escrever
bobagem; aqui faria a IA **agir**.

Por isso as ações não carregam alvo livre. O veículo vem da ocorrência, nunca
do texto — o cliente pode dizer "inative a placa XYZ1234" o quanto quiser, que
a placa que vai é a do evento que abriu a conversa.

## Por que "enquanto no local" e não uma data

Decisão da Central, confirmada pela operação.

O desenho original perguntava a data de saída da oficina. O gestor mostrou por
que não funciona: *"o cliente informa que fica em manutenção até as 17h, chega
18h40, gera outra remoção, e ele recebe nova notificação e tem de confirmar de
novo"*. Data prometida por cliente é estimativa, e oficina atrasa.

Inativar **enquanto o veículo estiver no local** elimina a data errada como
classe de problema, em vez de tratá-la caso a caso. O cliente precisa saber
disso — e é por isso que a IA diz, em vez de fazer calado.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from central_ia.observability.logging import logger

log = logger(__name__)


class Acao(StrEnum):
    """As únicas coisas que uma conversa pode pedir ao sistema da Bahrd.

    **Fechado de propósito.** Acrescentar exige editar este arquivo, o que
    significa revisão de código — e é exatamente a fricção que se quer entre
    uma conversa de WhatsApp e uma escrita no banco da empresa.

    As duas primeiras parecem uma com parâmetro diferente e **não são**. Uma
    está presa ao local e a outra ao relógio; confundi-las desativa o alarme de
    um caminhão que está justamente se movendo. A regra é:
    operações diferentes têm nomes diferentes.
    """

    #: Ignorar eventos deste veículo enquanto ele estiver **onde está agora**.
    #: Remoção de bateria em oficina, pátio, base do cliente.
    INATIVAR_ENQUANTO_NO_LOCAL = "inativar_enquanto_no_local"

    #: Ignorar eventos deste veículo por um **tempo**, onde quer que ele vá.
    #: Movimento sem ignição: o caminhão está no guincho e muda de lugar.
    INATIVAR_POR_PERIODO = "inativar_por_periodo"

    #: Regra permanente: este alarme não dispara neste local. Chave geral
    #: desligada todo dia no mesmo pátio, no mesmo horário.
    CRIAR_REGRA_DE_BASE = "criar_regra_de_base"

    #: Encerrar o evento no sistema da Bahrd com o desfecho apurado.
    FINALIZAR_EVENTO = "finalizar_evento"


@dataclass
class Tratativa:
    """Uma decisão da conversa, esperando execução.

    `parametros` é dicionário porque cada ação pede coisas diferentes, mas o que
    entra ali é montado pelo **código** a partir da ocorrência e do que a IA
    apurou — nunca copiado de texto do cliente. Ver `pedir`.
    """

    ocorrencia_id: str
    veiculo: str
    acao: Acao
    parametros: dict[str, str] = field(default_factory=dict)
    #: O que a IA entendeu, em português, para o operador ler sem decifrar nada.
    resumo: str = ""
    pedida_em: datetime = field(default_factory=lambda: datetime.now(UTC))
    executada_em: datetime | None = None
    #: `None` enquanto pendente; o que a Bahrd respondeu depois.
    resultado: str | None = None

    @property
    def pendente(self) -> bool:
        return self.executada_em is None


class Tratativas:
    """As tratativas da POC, em memória.

    Mesma escolha do `Sessoes`, e pelo mesmo motivo: reiniciar o contêiner
    limpa tudo, e nesta fase isso é conveniência de demonstração e não perda.
    O plano de Redis do doc 16 cobre as duas quando chegar a hora.
    """

    def __init__(self) -> None:
        self._itens: list[Tratativa] = []

    def pedir(
        self,
        ocorrencia_id: str,
        veiculo: str,
        acao: Acao,
        resumo: str,
        **parametros: str,
    ) -> Tratativa:
        """Registra o que a conversa decidiu. **Não executa nada.**

        `veiculo` vem da ocorrência, e é o chamador que garante isso. Se algum
        dia ele vier de texto do cliente, esta é a linha onde a regra 3 do doc
        28 foi violada.
        """
        t = Tratativa(
            ocorrencia_id=ocorrencia_id,
            veiculo=veiculo,
            acao=acao,
            parametros=parametros,
            resumo=resumo,
        )
        self._itens.append(t)
        log.info(
            "tratativa_pedida",
            ocorrencia=ocorrencia_id,
            veiculo=veiculo,
            acao=acao.value,
            parametros=parametros,
        )
        return t

    def pendentes(self) -> list[Tratativa]:
        """Da mais antiga para a mais nova: quem espera há mais tempo vem antes."""
        return [t for t in self._itens if t.pendente]

    def da_ocorrencia(self, ocorrencia_id: str) -> list[Tratativa]:
        return [t for t in self._itens if t.ocorrencia_id == ocorrencia_id]

    def todas(self) -> list[Tratativa]:
        return list(self._itens)

    def limpar(self) -> None:
        """Só para teste."""
        self._itens.clear()


#: A tabela viva do processo.
TRATATIVAS = Tratativas()


class ExecutorDaBahrd:
    """O que vai falar com o sistema da Bahrd. Hoje, ninguém.

    ⚠️ **Esta classe existe para NÃO fazer nada, e isso é o ponto.** Ela marca
    exatamente onde a chamada à API vai entrar, com a assinatura que ela vai
    ter, e mantém o resto do código escrito contra a versão final desde já.

    Quando a TI liberar a escrita, o corpo de `executar` deixa de registrar e
    passa a chamar — e nem a rota nem a conversa nem o painel mudam.

    Ela **não** valida a ação: quem valida é o tipo `Acao`, e isso é melhor,
    porque uma ação inválida nem chega a existir como objeto.
    """

    #: Por que ainda não executa. Vai para o painel, para o operador não achar
    #: que a IA prometeu e não cumpriu.
    MOTIVO = "A API de escrita da Bahrd ainda não existe."

    async def executar(self, tratativa: Tratativa) -> str:
        log.info(
            "tratativa_nao_executada",
            ocorrencia=tratativa.ocorrencia_id,
            acao=tratativa.acao.value,
            motivo=self.MOTIVO,
        )
        return self.MOTIVO


EXECUTOR = ExecutorDaBahrd()
