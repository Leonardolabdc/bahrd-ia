"""Tradução do evento da plataforma da Bahrd para o modelo canônico.

Escrito contra o export real (`docs/exemplos/Relatorio de Eventos.xls`, 12/08/2026).
O mesmo módulo serve o webhook quando ele existir: o que muda é de onde vêm os
campos, não o que eles significam.

Quatro coisas do formato de origem obrigam o desenho deste parser:

1. **`Dados` é texto multilinha `chave: valor`, e a ordem das chaves varia**
   entre linhas do mesmo relatório. Leitura por chave, nunca por posição.
2. **Campos são opcionais** — `contador` aparece em uma linha e não na outra.
   Tudo que não é essencial é `None`.
3. **Não existe identificador de evento.** A plataforma não emite um. A chave
   de idempotência é derivada de forma determinística (ver `_derivar_id`), e é
   ela que impede a mesma ocorrência de nascer duas vezes.
4. **`Tipo Evento` vem colado ao nome da cerca**, sem separador:
   ``"Entrou na cerca TESTE.HUDSON.PONTO DE INTERESSE"``. Sem separar os dois,
   cada cerca cadastrada viraria um tipo de evento novo.

Horários chegam **sem fuso**, em horário de Brasília (confirmado com a Bahrd).
São convertidos para UTC na entrada: a trilha de auditoria não pode depender do
fuso de quem escreveu.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from central_ia.domain import eventos

#: Sem horário de verão desde 2019, mas a zona IANA cobre uma eventual volta.
FUSO_BAHRD = ZoneInfo("America/Sao_Paulo")
UTC = ZoneInfo("UTC")

_FORMATO_DATA = "%d/%m/%Y %H:%M:%S"

# "MOVEL GL 320 ( 860201061136415)" — o espaço depois do parêntese é do sistema.
_PLACA = re.compile(r"^\s*(?P<descricao>.*?)\s*\(\s*(?P<imei>\d+)\s*\)\s*$")

# "4.0 kmh", "444 Km", "0 kmh" — unidade grudada e caixa inconsistente.
_NUMERO = re.compile(r"-?\d+(?:[.,]\d+)?")


class EventoRastreamento(BaseModel):
    """Evento normalizado, pronto para o motor de políticas."""

    evento_externo_id: str = Field(description="Chave de idempotência derivada — ver _derivar_id.")

    rotulo_link: str = Field(description="Nome do evento como a plataforma o escreve.")
    codigo_evento: str | None = Field(
        default=None,
        description="Código do nosso catálogo. `None` significa fora de escopo — "
        "e fora de escopo nunca vira atendimento automático.",
    )
    objeto_geografico: str | None = Field(
        default=None, description="Cerca ou ponto de interesse citado no evento."
    )

    #: O export em XLS sempre traz IMEI; o webhook (doc 08) **não**. Opcional
    #: por causa dele — quem lê precisa tratar ausência, não presumir.
    imei: str | None = None
    veiculo: str
    grupo: str | None = None
    motorista: str | None = None
    #: Só o webhook traz. É o campo que permite a IA falar com alguém sem
    #: depender de cadastro externo — ver doc 08.
    telefone_contato: str | None = None

    momento: datetime = Field(description="Data/Hora Posição, em UTC.")
    momento_gravacao: datetime | None = None
    momento_finalizado: datetime | None = None

    latitude: float | None = None
    longitude: float | None = None
    endereco: str | None = None

    velocidade_kmh: float | None = None
    velocidade_limite_kmh: float | None = None
    direcao: int | None = None
    ignicao: bool | None = None
    panico: bool | None = None
    entradas: int | None = None
    saidas: int | None = None
    odometro_km: float | None = None
    horimetro: float | None = None
    contador: int | None = None

    bruto: dict[str, str] = Field(
        default_factory=dict,
        description="Payload original do campo `Dados`. Guardado inteiro porque "
        "campo que hoje não usamos é campo que amanhã explica um caso.",
    )

    @property
    def em_escopo(self) -> bool:
        return self.codigo_evento is not None


# ─────────────────────────────── auxiliares ───────────────────────────────


def _numero(texto: str | None) -> float | None:
    """Extrai o número de textos como `4.0 kmh` ou `444 Km`."""
    if not texto:
        return None
    achado = _NUMERO.search(texto)
    return float(achado.group().replace(",", ".")) if achado else None


def _inteiro(texto: str | None) -> int | None:
    valor = _numero(texto)
    return int(valor) if valor is not None else None


def _booleano(texto: str | None) -> bool | None:
    """`0`/`1` da telemetria. Ausente vira `None`, não `False`.

    A diferença importa: "o rastreador disse que a ignição está desligada" e
    "o rastreador não informou a ignição" levam a decisões diferentes.
    """
    valor = _inteiro(texto)
    return None if valor is None else bool(valor)


def _momento(texto: str | None) -> datetime | None:
    """Converte horário de Brasília (sem fuso na origem) para UTC."""
    if not texto or not texto.strip():
        return None
    local = datetime.strptime(texto.strip(), _FORMATO_DATA).replace(tzinfo=FUSO_BAHRD)
    return local.astimezone(UTC)


def parse_dados(texto: str | None) -> dict[str, str]:
    """Lê o campo `Dados` — um `chave: valor` por linha, ordem variável."""
    if not texto:
        return {}
    pares: dict[str, str] = {}
    for linha in texto.splitlines():
        if ":" not in linha:
            continue
        chave, _, valor = linha.partition(":")
        chave = chave.strip().lower()
        if chave:
            pares[chave] = valor.strip()
    return pares


def parse_placa(texto: str | None) -> tuple[str, str]:
    """Separa `MOVEL GL 320 ( 860201061136415)` em descrição e IMEI."""
    if not texto:
        return "", ""
    if achado := _PLACA.match(texto):
        return achado.group("descricao"), achado.group("imei")
    return texto.strip(), ""


def separar_tipo_evento(texto: str | None) -> tuple[str, str | None]:
    """Separa o nome do evento do nome da cerca/ponto grudado nele.

    A separação é por **prefixo conhecido**, não por heurística de texto: só o
    catálogo sabe onde termina o nome do evento. Rótulo desconhecido volta
    inteiro e sem objeto — e um evento que não casa com o catálogo nunca vira
    atendimento automático.
    """
    if not texto:
        return "", None
    limpo = " ".join(texto.split())

    # Do rótulo mais longo para o mais curto: "Entrou na cerca" é prefixo de
    # nada, mas rótulos futuros podem se conter mutuamente.
    for tipo in sorted(eventos.CATALOGO, key=lambda t: len(t.rotulo), reverse=True):
        if limpo == tipo.rotulo:
            return tipo.rotulo, None
        if limpo.startswith(tipo.rotulo + " "):
            return tipo.rotulo, limpo[len(tipo.rotulo) :].strip() or None

    return limpo, None


def _derivar_id(imei: str, rotulo: str, objeto: str | None, momento: datetime) -> str:
    """Chave de idempotência, já que a plataforma não emite identificador.

    Escolha dos componentes: o mesmo veículo, no mesmo instante, com o mesmo
    tipo de evento e sobre a mesma cerca **é** o mesmo evento — foi o que o
    relatório de 12/08 mostrou, com a plataforma gravando a mesma entrada duas
    vezes com payloads levemente diferentes.

    Não entra nada do payload: se entrasse, as duas cópias gerariam ids
    diferentes e a duplicata passaria.
    """
    semente = f"{imei}|{rotulo}|{objeto or ''}|{momento.isoformat()}"
    return hashlib.sha256(semente.encode("utf-8")).hexdigest()[:32]


# ──────────────────────────────── entrada ────────────────────────────────


def parse_linha_relatorio(linha: dict[str, str | None]) -> EventoRastreamento:
    """Converte uma linha do Relatório de Eventos no modelo canônico.

    `linha` é o mapa coluna → valor, com os nomes de cabeçalho da planilha.
    """
    rotulo, objeto = separar_tipo_evento(linha.get("Tipo Evento"))
    veiculo, imei = parse_placa(linha.get("Placa"))
    dados = parse_dados(linha.get("Dados"))

    momento = _momento(linha.get("Data/Hora Posição"))
    if momento is None:
        raise ValueError("Evento sem Data/Hora Posição — não há como ordenar nem deduplicar.")

    latitude = longitude = None
    if bruto := (linha.get("Latitude/Longitude") or "").strip():
        partes = bruto.split("/")
        if len(partes) == 2:
            latitude, longitude = _numero(partes[0]), _numero(partes[1])

    tipo = eventos.por_rotulo(rotulo)

    return EventoRastreamento(
        evento_externo_id=_derivar_id(imei, rotulo, objeto, momento),
        rotulo_link=rotulo,
        codigo_evento=tipo.codigo if tipo else None,
        objeto_geografico=objeto,
        imei=imei,
        veiculo=veiculo,
        grupo=(linha.get("Grupo") or "").strip() or None,
        motorista=(linha.get("Motorista") or "").strip() or None,
        momento=momento,
        momento_gravacao=_momento(linha.get("Data/hora gravação")),
        momento_finalizado=_momento(linha.get("Data/Hora finalizado")),
        latitude=latitude,
        longitude=longitude,
        endereco=(linha.get("Endereço") or "").strip() or None,
        # `Velocidade Atingida` é a do evento; `Velocidade`, o limite configurado.
        velocidade_kmh=(
            _numero(linha.get("Velocidade Atingida")) or _numero(dados.get("velocidade"))
        ),
        velocidade_limite_kmh=_numero(linha.get("Velocidade")),
        direcao=_inteiro(dados.get("direcao")),
        ignicao=_booleano(dados.get("ignicao")),
        panico=_booleano(dados.get("panico")),
        entradas=_inteiro(dados.get("entradas")),
        saidas=_inteiro(dados.get("saidas")),
        odometro_km=_numero(dados.get("odometro")),
        horimetro=_numero(dados.get("horimetro")),
        contador=_inteiro(dados.get("contador")),
        bruto=dados,
    )


def deduplicar(lista: list[EventoRastreamento]) -> list[EventoRastreamento]:
    """Remove repetições preservando a ordem de chegada.

    A primeira ocorrência vence. As cópias costumam diferir só em campos
    acessórios (`contador`), e escolher a primeira mantém o resultado estável
    entre reprocessamentos do mesmo relatório.
    """
    vistos: set[str] = set()
    unicos: list[EventoRastreamento] = []
    for evento in lista:
        if evento.evento_externo_id in vistos:
            continue
        vistos.add(evento.evento_externo_id)
        unicos.append(evento)
    return unicos
