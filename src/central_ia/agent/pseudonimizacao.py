"""Troca de identidade na fronteira com o LLM.

A IA conduz a conversa inteira usando apelidos — nunca o nome, a placa ou o
endereço reais do cliente. O mapa nasce quando a ocorrência abre e vale até o
fim dela: o mesmo apelido do primeiro ao último turno, porque trocar no meio
confundiria o modelo sobre quem é quem.

Duas camadas, para dois problemas diferentes:

1. **Dado conhecido** (nome, placa, endereço) — o sistema já tem o valor
   guardado na sessão. Troca literal, **reversível**: o apelido volta a ser o
   valor real depois que a IA responde, antes de a mensagem sair pelo
   WhatsApp ou virar áudio. A OpenRouter/Anthropic nunca recebe o dado cru.
2. **Dado desconhecido** (CPF, telefone de terceiro, e-mail que o cliente
   solta no meio da conversa) — o sistema não tem como saber o valor de
   antemão. Detecção por padrão, vira marcador genérico, **não** reversível:
   a IA não precisa repetir esse dado de volta, só responder em torno dele.

O que fica de fora, de propósito: nome de terceiro solto em texto livre
("fala com o Roberto"). Pegar isso sem um dicionário de nomes brasileiros
gera falso positivo a cada "oi", "ok" e "tudo bem" — o custo é maior que o
ganho. Fica registrado como limitação conhecida, não como cobertura
inexistente disfarçada de completa.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from central_ia.ports.llm import Mensagem

# ─────────────────────── camada 2 · padrões estruturados ───────────────────

#: Telefone brasileiro, com ou sem DDD, com ou sem o nono dígito, com ou sem
#: pontuação. Generoso de propósito: um falso positivo aqui vira "[TELEFONE]"
#: no meio da frase, que o operador ainda entende; um falso negativo vaza o
#: número de verdade para um provedor de LLM.
_TELEFONE = re.compile(r"(?:\+?55\s?)?\(?\d{2}\)?[\s.-]?9?\d{4}[\s.-]?\d{4}")

#: CPF, com ou sem pontuação. Não valida dígito verificador — não é o
#: trabalho desta função confirmar que o CPF existe, só que o formato existe.
_CPF = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}")


@dataclass(frozen=True)
class MapaDeApelidos:
    """Par (valor real → apelido) para uma ocorrência só.

    A ordem importa: pares com valor mais específico (placa, endereço) antes
    dos mais genéricos, para um valor curto não comer parte de um mais longo.
    """

    pares: tuple[tuple[str, str], ...]

    def sanitizar(self, texto: str) -> str:
        """O que vai **para** o LLM passa por aqui — nunca o contrário."""
        for valor_real, apelido in self.pares:
            if valor_real:
                texto = re.sub(
                    r"\b" + re.escape(valor_real) + r"\b",
                    apelido,
                    texto,
                    flags=re.IGNORECASE,
                )
        texto = _CPF.sub("[CPF]", texto)
        texto = _EMAIL.sub("[EMAIL]", texto)
        texto = _TELEFONE.sub("[TELEFONE]", texto)
        return texto

    def reidentificar(self, texto: str) -> str:
        """O que **volta** do LLM passa por aqui, antes de virar mensagem."""
        for valor_real, apelido in self.pares:
            if valor_real:
                texto = re.sub(
                    r"\b" + re.escape(apelido) + r"\b",
                    valor_real,
                    texto,
                    flags=re.IGNORECASE,
                )
        return texto


#: Apelidos fixos. Não precisam ser únicos entre ocorrências diferentes — o
#: mapa vive só na memória de uma conversa, nunca é comparado com o de outra.
_APELIDO_NOME = "Cliente"
_APELIDO_PLACA = "VEIC-001"
_APELIDO_ENDERECO = "o local informado"


def montar_mapa(
    *, nome: str | None, placa: str | None, endereco: str | None
) -> MapaDeApelidos:
    """Monta o mapa uma vez, na abertura da ocorrência.

    Os três campos são opcionais porque nem todo evento tem os três —
    endereço pode faltar, por exemplo. Campo ausente não entra no mapa: não
    há valor real para trocar, então não há o que sanitizar nem reidentificar.
    """
    pares: list[tuple[str, str]] = []
    if endereco:
        pares.append((endereco, _APELIDO_ENDERECO))
    if placa:
        pares.append((placa, _APELIDO_PLACA))
    if nome:
        pares.append((nome, _APELIDO_NOME))
    return MapaDeApelidos(tuple(pares))


def sanitizar_historico(
    historico: list[Mensagem], mapa: MapaDeApelidos
) -> list[Mensagem]:
    """Cópia do histórico com cada `conteudo` sanitizado.

    **Nunca** muta `historico` — é a lista de verdade que o painel mostra ao
    operador e que fica salva na sessão. O que vai para o LLM é sempre uma
    cópia à parte.
    """
    return [
        Mensagem(papel=m.papel, conteudo=mapa.sanitizar(m.conteudo))
        for m in historico
    ]
