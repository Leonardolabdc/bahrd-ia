"""Tradução do **payload JSON** da Bahrd para o modelo canônico.

Segunda entrada, não substituto: `link.py` lê o export em XLS (histórico), este
lê o que a plataforma manda no webhook. **O modelo canônico é o mesmo** — muda o
tradutor, não o significado.

Formato acordado com o gestor da Central em 19/08/2026, documentado em
`a documentação interna do projeto`:

```json
{
  "rotulo": "Veículo ABC-1234",
  "data_hora_evento": "2026-08-19 15:10:00",
  "latitude": -25.4504094,
  "longitude": -49.256198,
  "tipo_evento": "Movimento com ignição desligada",
  "contato_nome": "João da Silva",
  "contato_telefone": "41999999999"
}
```

Quatro decisões que o formato de origem obriga:

1. **`rotulo` é o VEÍCULO, não o evento.** No modelo canônico `rotulo_link` é o
   nome do evento. Mapear por semelhança de nome inverte os dois, e o erro é
   silencioso: a placa vira tipo de evento e cai fora de escopo.
2. **Não vem IMEI.** O XLS traz, o webhook não. A identidade do veículo passa a
   ser o texto de `rotulo`.
3. **Não vem identificador de evento** — nem aqui nem no XLS. A chave de
   idempotência é derivada (ver `_derivar_id`). Se a Bahrd passar a mandar um
   `id`, ele é aproveitado: o campo é lido quando existe.
4. **Telefone sem DDI.** A Bahrd só atende no Brasil (confirmado em 19/08/2026),
   então `+55` é acrescentado na entrada. Normalizar aqui evita que cada ponto
   de uso invente o seu formato.

Horários chegam **sem fuso, em horário de Brasília** (confirmado). Convertidos
para UTC na entrada, pela mesma razão do `link.py`: trilha de auditoria não pode
depender do fuso de quem escreveu.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any

from central_ia.domain import eventos
from central_ia.integrations.rastreamento.bahrd import (
    FUSO_BAHRD,
    UTC,
    EventoRastreamento,
)
from central_ia.observability.logging import logger

log = logger(__name__)

#: Qualquer sequência de espaço, tabulação ou quebra de linha.
_ESPACOS = re.compile(r"\s+")

#: Tetos por campo. Nome de gente e endereço não passam disso; acima é colagem.
LIMITE_NOME = 120
LIMITE_ENDERECO = 200
LIMITE_ROTULO = 120

#: A Bahrd atende só no Brasil — confirmado com o gestor em 19/08/2026.
DDI_BRASIL = "55"

#: `2026-08-19 15:10:00` é o formato do exemplo. O ISO com `T` é aceito porque
#: custa nada e é o erro de serialização mais provável do outro lado.
_FORMATOS_DATA = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S")

#: Campos sem os quais não existe atendimento: o que aconteceu, com quem e onde.
_OBRIGATORIOS = ("rotulo", "data_hora_evento", "tipo_evento")


class PayloadInvalido(ValueError):
    """O payload não tem o mínimo para virar ocorrência.

    Vira `422` no webhook, nunca `500`: a plataforma da Bahrd precisa saber que o
    problema é o conteúdo, não a nossa disponibilidade.
    """


def _momento(texto: str) -> datetime:
    """Texto sem fuso, em horário de Brasília, para `datetime` em UTC."""
    for formato in _FORMATOS_DATA:
        try:
            ingenuo = datetime.strptime(texto.strip(), formato)
        except ValueError:
            continue
        return ingenuo.replace(tzinfo=FUSO_BAHRD).astimezone(UTC)
    raise PayloadInvalido(f"data_hora_evento fora dos formatos aceitos: {texto!r}")


#: Como a Bahrd pode batizar o logradouro do evento, em ordem de preferência.
#:
#: **A lista existe porque o nome do campo ainda não foi combinado.** Hoje a
#: plataforma não manda endereço nenhum e o `📍 Local:` da notificação sai como
#: "veja o mapa acima" (doc 08). No dia em que a TI incluir o campo, ele pode
#: chegar com qualquer um destes nomes — e ler só `endereco` faria o logradouro
#: ser descartado em silêncio, com a mensagem saindo bonita e ninguém sabendo.
_CHAVES_DE_ENDERECO = ("endereco", "logradouro", "endereco_completo", "address")


def _endereco(payload: dict[str, Any]) -> str | None:
    """O logradouro do evento, sob qualquer um dos nomes conhecidos.

    Registra qual nome chegou. Isso é o ponto: no primeiro evento real com
    endereço, o log diz exatamente como a Bahrd chama o campo, e a lista acima
    deixa de ser palpite.

    Quando não vem nenhum e há coordenada, avisa **com as chaves do payload**.
    É a diferença entre descobrir o nome certo lendo uma linha de log e
    descobrir semanas depois que o endereço sempre esteve lá.
    """
    for chave in _CHAVES_DE_ENDERECO:
        # Higiene de fronteira: isto vira contexto do modelo e parâmetro de
        # template — ver `_texto`.
        valor = _texto(payload.get(chave), LIMITE_ENDERECO)
        if valor:
            if chave != _CHAVES_DE_ENDERECO[0]:
                log.info("bahrd_endereco_com_outro_nome", chave=chave)
            return valor

    if payload.get("latitude") is not None:
        # Só as chaves, nunca os valores: o payload tem nome e telefone.
        log.info("bahrd_evento_sem_endereco", chaves=sorted(str(c) for c in payload))
    return None


def _telefone(bruto: Any) -> str | None:
    """`41999999999` → `+5541999999999`.

    Aceita o que a plataforma mandar — com máscara, com DDI, com `+` — e devolve
    sempre E.164. Devolve `None` em vez de lixo: telefone meia-boca faz a IA
    escrever para o número errado, e isso é pior que não escrever.
    """
    if bruto is None:
        return None
    digitos = "".join(c for c in str(bruto) if c.isdigit())
    if not digitos:
        return None
    if not digitos.startswith(DDI_BRASIL):
        digitos = DDI_BRASIL + digitos
    # 55 + DDD(2) + 8 ou 9 dígitos. Fora disso não é telefone brasileiro válido,
    # e chutar um dígito a mais ou a menos manda mensagem para um estranho.
    if not (12 <= len(digitos) <= 13):
        return None
    return f"+{digitos}"


#: Marcas de controle que o agente lê **na saída do modelo**. Num campo de
#: cadastro elas não têm o que fazer — e é justamente por isso que valem para
#: quem ataca.
_MARCA_DE_CONTROLE = re.compile(r"\[\[?[A-ZÇÃÕ_]{4,}[^\]]*\]?\]")


def _texto(bruto: Any, limite: int) -> str | None:
    """Campo de texto do payload, seguro para entrar no prompt.

    **Injeção indireta, e é o único caminho em que a besteira chega a um
    inocente.** O nome do contato vem do payload da Bahrd e vai parar no contexto
    do modelo:

        payload["contato_nome"] → evento.motorista → dados["interlocutor"] → prompt

    Quem escreve não é o motorista, é quem posta no webhook — e a vítima é o
    motorista, que recebe no celular o que a IA responder. Enquanto a assinatura
    HMAC estiver desligada (doc 07), qualquer um que descubra a URL posta.

    Três limpezas, e a primeira é a que mais importa:

    * **Quebra de linha vira espaço.** O `contexto_inicial` monta o contexto
      como linhas `- chave: valor`. Um nome com `\\n` injeta **uma linha nova**
      ali dentro, e quem escolhe o texto escolhe o que a IA lê como fato do
      cadastro. O exemplo aqui era o guincho credenciado, que saiu do contexto
      em 03/09/2026; a injeção continua valendo para qualquer chave, porque o
      que ela explora é o formato, não o campo.
    * **Marca de controle sai.** `[[ENCERRAR:...]]` num campo de cadastro é
      convite para o modelo repetir e o parser aceitar.
    * **Teto de tamanho.** Nome de gente não tem 4 KB.

    Não é validação de formato: cadastro real vem torto, com apelido, com
    "(motorista)" no fim, e nada disso pode ser recusado. É higiene de fronteira.
    """
    if bruto is None or bruto == "":
        return None
    limpo = _MARCA_DE_CONTROLE.sub("", str(bruto))
    limpo = _ESPACOS.sub(" ", limpo).strip()
    return limpo[:limite].strip() or None


def _numero(bruto: Any) -> float | None:
    """Coordenada que pode vir número ou texto. Ausência não é erro."""
    if bruto is None or bruto == "":
        return None
    try:
        return float(str(bruto).replace(",", "."))
    except ValueError:
        return None


def _derivar_id(veiculo: str, rotulo: str, momento: datetime) -> str:
    """Chave de idempotência, já que a plataforma não emite identificador.

    Sem IMEI, a identidade do veículo é o texto de `rotulo`. **É mais frágil que
    a do `link.py`**: dois eventos do mesmo veículo, do mesmo tipo, no mesmo
    segundo, colapsam num só. Aceitável porque a alternativa — deixar passar
    duplicata — é pior, e porque a plataforma da Bahrd já gravou a mesma entrada
    duas vezes no relatório de 12/08.

    Some no dia em que a Bahrd mandar um `id` próprio. É o pedido de maior
    retorno e menor esforço da lista do doc 08.
    """
    semente = f"{veiculo}|{rotulo}|{momento.isoformat()}"
    return hashlib.sha256(semente.encode("utf-8")).hexdigest()[:32]


def parse_evento_webhook(payload: dict[str, Any]) -> EventoRastreamento:
    """Converte o JSON do webhook da Bahrd no modelo canônico.

    Levanta `PayloadInvalido` quando falta o mínimo. Campo desconhecido é
    guardado em `bruto`, nunca descartado: campo que hoje não usamos é campo que
    amanhã explica um caso.
    """
    faltando = [c for c in _OBRIGATORIOS if not payload.get(c)]
    if faltando:
        raise PayloadInvalido(f"campos obrigatórios ausentes: {', '.join(faltando)}")

    # A placa também vira contexto do modelo e parâmetro do template. O tipo do
    # evento não precisa de teto: ele é casado contra o catálogo logo abaixo, e
    # o que não bate vira `None`.
    veiculo = _texto(payload["rotulo"], LIMITE_ROTULO) or ""
    rotulo_evento = str(payload["tipo_evento"]).strip()
    momento = _momento(str(payload["data_hora_evento"]))

    # Fora do catálogo é `None` — e fora de escopo nunca vira atendimento
    # automático. A regra é do `link.py`; repeti-la aqui é deliberado.
    tipo = eventos.por_rotulo(rotulo_evento)

    return EventoRastreamento(
        # Aproveita o `id` da plataforma se um dia ele existir; deriva enquanto não.
        evento_externo_id=str(payload.get("id") or _derivar_id(veiculo, rotulo_evento, momento)),
        rotulo_link=rotulo_evento,
        codigo_evento=tipo.codigo if tipo else None,
        imei=str(payload["imei"]).strip() if payload.get("imei") else None,
        veiculo=veiculo,
        # Higiene de fronteira nos campos que viram contexto do modelo — ver
        # `_texto`. O nome vem de quem posta no webhook, não do motorista.
        motorista=_texto(payload.get("contato_nome"), LIMITE_NOME),
        telefone_contato=_telefone(payload.get("contato_telefone")),
        momento=momento,
        latitude=_numero(payload.get("latitude")),
        longitude=_numero(payload.get("longitude")),
        endereco=_endereco(payload),
        bruto={str(c): str(v) for c, v in payload.items() if v is not None},
    )
