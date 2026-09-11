"""API do painel do operador.

Hoje serve a amostra de :mod:`central_ia.api.amostra`. No Sprint 2 o corpo de
cada função passa a ler de `ocorrencia` (Oracle) e `conversa`/`mensagem`
(MySQL) — **as assinaturas e os esquemas não mudam**, então o painel não muda.

O `kill_switch` fica aqui e não no `agent-core` de propósito: desligar a IA é
uma ação de supervisão, e precisa funcionar mesmo que o agente esteja travado.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from central_ia.agent.prompts import versao_dos_prompts
from central_ia.api import amostra
from central_ia.api.esquemas_painel import (
    Encerrada,
    Encerrados,
    EquipamentoReincidente,
    EventoAuditoria,
    Fila,
    ItemFila,
    Metricas,
    Ocorrencia,
    PassoRoteiro,
    Turno,
)
from central_ia.api.seguranca import exigir_token_do_painel
from central_ia.config import settings
from central_ia.domain import eventos
from central_ia.domain.eventos import POLITICA_VERSAO
from central_ia.integrations.llm import construir_cliente_llm
from central_ia.integrations.rastreamento import construir_fonte
from central_ia.orchestration import numeros_removidos
from central_ia.orchestration.pipeline import Pipeline, Resultado
from central_ia.orchestration.sessao_whatsapp import SESSOES, Sessao

# A tranca vale para **todas** as rotas do painel, aplicada aqui e não em cada
# uma: rota nova nasce protegida, sem depender de alguém lembrar. Ver o porquê
# em `api/seguranca.py`.
router = APIRouter(
    prefix="/painel",
    tags=["painel"],
    dependencies=[Depends(exigir_token_do_painel)],
)

#: Tudo é gravado em UTC; a tela mostra o fuso de quem está de plantão. A
#: conversão acontece só aqui, na borda — nunca no armazenamento.
FUSO_PAINEL = ZoneInfo("America/Sao_Paulo")

#: Simulações desta sessão, mais recentes primeiro. Em memória de propósito:
#: são demonstração, e o Sprint 2 troca isto pelos repositórios do Oracle e do
#: MySQL sem mudar o contrato da API.
_SIMULADAS: list[Resultado] = []


def _como_item(resultado: Resultado) -> ItemFila:
    """Traduz o resultado do pipeline para a linha da fila."""
    tipo = eventos.por_rotulo(resultado.tipo_evento)
    grau = {"CRITICA": "critica", "ALTA": "alta", "MEDIA": "media", "BAIXA": "baixa"}[
        resultado.criticidade
    ]

    # O horário vem do primeiro passo da auditoria — o instante em que o evento
    # chegou —, convertido para Brasília, que é o fuso de quem lê a tela.
    recebido = resultado.auditoria[0].momento if resultado.auditoria else None
    local = recebido.astimezone(FUSO_PAINEL) if recebido else None

    return ItemFila(
        momento=f"{local:%H:%M}" if local else None,
        dia=f"{local:%d/%m/%Y}" if local else None,
        momento_completo=f"{local:%d/%m/%Y às %H:%M:%S}" if local else None,
        latitude=resultado.latitude,
        longitude=resultado.longitude,
        endereco=resultado.endereco,
        ocorrencia_id=resultado.ocorrencia_id,
        grau=grau,  # type: ignore[arg-type]
        tipo_evento=resultado.tipo_evento,
        canal=resultado.canal or "LIGACAO",  # type: ignore[arg-type]
        placa=resultado.ocorrencia_id.split("-")[-1],
        interlocutor="simulação",
        nota="Encerrada pela IA" if resultado.estado == "ENCERRADA_PELA_IA" else "Simulação",
        decorrido_s=0,
        sla_s=tipo.janela_s if tipo else 60,
        leitura_ia=resultado.briefing if not resultado.elegivel_ia else None,
        tem_detalhe=True,
    )


def _item_da_sessao(s: Sessao) -> ItemFila:
    """Uma conversa de WhatsApp real, como linha da fila.

    A narração vem do estado da sessão, nunca do modelo — mesma regra do resto
    do painel. Se o LLM escrevesse estas frases, a tela poderia mentir sobre o
    que ele fez.
    """
    if s.encerrada:
        frase = f"Encerrada · {s.motivo_encerramento}"
    elif s.turnos_ia == 0:
        frase = "Abrindo a conversa no WhatsApp"
    else:
        frase = f"Aguardando a resposta do cliente · turno {s.turnos_ia}"

    nota = None
    if s.probabilidade_real is not None:
        nota = f"Triagem: {s.probabilidade_real}% de chance de ser real"

    return ItemFila(
        ocorrencia_id=s.ocorrencia_id,
        grau=s.grau,  # type: ignore[arg-type]
        tipo_evento=s.tipo.rotulo,
        canal=s.canal,  # type: ignore[arg-type]
        placa=s.dados.get("placa", "—"),
        interlocutor=f"{s.dados.get('interlocutor', 'cliente')} · WhatsApp real",
        nota=nota,
        origem=s.origem,
        decorrido_s=int((datetime.now(UTC) - s.criada_em).total_seconds()),
        sla_s=s.tipo.janela_s,
        momento=f"{s.criada_em.astimezone(FUSO_PAINEL):%H:%M}",
        dia=f"{s.criada_em.astimezone(FUSO_PAINEL):%d/%m/%Y}",
        momento_completo=f"{s.criada_em.astimezone(FUSO_PAINEL):%d/%m/%Y às %H:%M:%S}",
        latitude=s.latitude,
        longitude=s.longitude,
        endereco=s.endereco,
        tem_detalhe=True,
        tem_ao_vivo=True,
        ao_vivo_real=True,
        roteiro=[PassoRoteiro(frase=frase, duracao_s=6, falando=not s.encerrada)],
        falas=[Turno(quem=f.quem, fala=f.texto) for f in s.falas],  # type: ignore[arg-type]
    )


@router.get("/fila", response_model=Fila, summary="Fila do operador e o que a IA está fazendo")
async def obter_fila() -> Fila:
    """Duas listas, deliberadamente separadas.

    "Precisa de você" e "A IA está fazendo" não são um filtro sobre a mesma
    lista: são papéis diferentes. Misturar as duas faria o operador varrer
    itens que não exigem ação dele — o oposto de "uma decisão por tela".

    As simulações que sobraram para o humano entram no topo, para aparecerem
    assim que o botão é apertado. As que a IA encerrou **não** entram: elas vão
    para a aba Encerrados. Um caso resolvido ocupando espaço na fila de quem
    está de plantão é ruído, e ruído em fila de plantão custa atenção.
    """
    fila = amostra.fila()
    pendentes = [r for r in _SIMULADAS if r.estado != "ENCERRADA_PELA_IA"]
    if pendentes:
        fila.precisa_de_voce = [_como_item(r) for r in pendentes] + fila.precisa_de_voce

    # Conversas de WhatsApp reais. Enquanto a IA está falando, a linha fica em
    # "Atendimento da IA"; quando ela escala, muda de aba — o operador não
    # precisa saber que veio de outro canal para entender o que fazer.
    for sessao in SESSOES.todas():
        if sessao.encerrada and not sessao.escalada:
            continue
        item = _item_da_sessao(sessao)
        if sessao.escalada:
            fila.precisa_de_voce.insert(0, item)
        else:
            fila.ia_esta_fazendo.insert(0, item)

    return fila


@router.get(
    "/ocorrencias/{ocorrencia_id}",
    response_model=Ocorrencia,
    summary="Detalhe da ocorrência, com briefing, conversa e trilha de auditoria",
)
async def obter_ocorrencia(ocorrencia_id: str) -> Ocorrencia:
    if sessao := SESSOES.por_id(ocorrencia_id):
        return _ocorrencia_da_sessao(sessao)

    for resultado in _SIMULADAS:
        if resultado.ocorrencia_id == ocorrencia_id:
            return _como_ocorrencia(resultado)

    if encontrada := amostra.ocorrencia(ocorrencia_id):
        return encontrada

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Ocorrência {ocorrencia_id} não encontrada.",
    )


#: O que `_atender` escreve em `interlocutor` quando o evento não traz nome.
#:
#: Fica aqui, e não escrito no meio da ficha, porque é um acoplamento real com
#: `api/rotas/eventos.py`: se o texto mudar lá e não aqui, a ficha volta a
#: mostrar "Cliente: o motorista" sem ninguém perceber.
_SEM_NOME = "o motorista"


def _nome_ou_vazio(interlocutor: str) -> str:
    return "" if interlocutor.strip().lower() == _SEM_NOME else interlocutor


def _supressao(s: Sessao) -> str:
    """Até quando os alarmes deste veículo estão desligados.

    Três estados, e a diferença entre eles é o que a aba de supressão existe
    para mostrar:

    * **sem prazo** — `veiculo_em_manutencao` e `local_e_base_do_cliente`
      suprimem *enquanto a situação durar*, e sair pelo relógio seria inventar
      um fim que ninguém combinou;
    * **prazo vencido** — passou a hora e ninguém confirmou que continua. É o
      que o operador precisa ver, e por isso vem escrito e não calculado na tela;
    * **com prazo** — o normal.

    Vazio quando o caso não suprime nada, e aí a linha some da ficha.
    """
    if not s.desativada:
        return ""
    if s.desativada_ate is None:
        return "até a situação mudar"
    ate = f"{s.desativada_ate.astimezone(FUSO_PAINEL):%H:%M}"
    return f"prazo vencido às {ate}" if s.desativacao_expirou else f"até {ate}"


def _coordenada(s: Sessao) -> str:
    """A posição do evento, no formato que se cola num mapa.

    ⚠️ **Linha própria, e não colada no logradouro.** As duas informações
    chegaram juntas em 03/09/2026 e o `ruff` reprovou a linha por passar de 100
    caracteres, o que era o sintoma certo de um problema de leitura: o texto do
    logradouro já traz o estado do veículo ("acostamento, ignição desligada"), e
    a coordenada virava um terceiro trecho depois do terceiro `·`.

    Separadas, cada uma responde a sua pergunta. O logradouro diz para uma
    pessoa onde é; a coordenada é o que se seleciona e cola, e selecionar um
    pedaço do meio de uma frase é pior que selecionar uma linha inteira.

    Ponto decimal, não vírgula: fica estranho num texto em português e é o
    formato que o Google Maps e o Waze aceitam colados.
    """
    if s.latitude is None or s.longitude is None:
        return ""
    return f"{s.latitude:.5f}, {s.longitude:.5f}"


def _ficha_da_sessao(s: Sessao, estado: str) -> dict[str, str]:
    """Só o que é fato: o que veio no evento e o que o nosso sistema mediu.

    ⚠️ **Enxugada em 03/09/2026, a pedido do Leonardo:** *"deixe somente
    informações que estão chegando no nosso json e tire todo o resto"*.

    ⛔ O problema não era o excesso, era a **origem**. A ficha misturava o que a
    Bahrd mandou com o que a fonte de amostra inventou, sem distinguir os dois. O
    payload real traz placa, telefone, nome do contato e, às vezes, endereço
    (doc 08). Cliente, gestor, guincho credenciado e modelo do veículo saíam da
    amostra — e apareciam na tela com a mesma cara de dado conferido.

    Num teste isso é ruim; no dia em que a fonte real entrar, é pior: o campo
    continua na tela e passa a estar **vazio**, e ninguém vai saber se o dado
    não veio ou se o veículo não tem.

    Campo sem valor não vira linha. Um rótulo com um travessão do lado ocupa
    espaço para dizer "não sei", e quem lê sob pressão lê isso como informação.
    """
    # A ordem conta uma história: em que situação está, depois qual veículo e
    # com quem falamos, depois onde aconteceu, e por último o que a IA gastou.
    # O "Número" ficava antes da "Placa" e separava o cliente do contato dele.
    campos = {
        # Primeira linha: é o que identifica o caso antes de qualquer outro dado.
        #
        # ⚠️ Também aparece como título da tela (`<h1>` em `Ocorrencia.tsx`), e a
        # repetição é deliberada: a ficha é um bloco retrátil que alguém lê, ou
        # copia, isolado do resto — e pela API ela chega sem título nenhum.
        "Evento": s.tipo.rotulo,
        # "Estado" era ambíguo numa tela de frota: lê-se como unidade federativa
        # antes de "situação do atendimento", ainda mais colado a uma placa.
        "Situação": estado,
        # ⚠️ Dizia "WhatsApp real, via Twilio" e estava **errado desde que
        # `CANAL_WHATSAPP` virou `meta`**: o texto era fixo e não acompanhou a
        # troca de canal. A ficha afirmava um intermediário que não está mais no
        # caminho. Sem o nome do provedor, o rótulo para de poder envelhecer.
        "Canal": "WhatsApp real",
        "Placa": s.dados.get("placa", ""),
        # ⚠️ `interlocutor` cai em "o motorista" quando o evento não traz
        # `contato_nome`. Esse texto é um substantivo genérico, não um nome:
        # mostrá-lo como "Cliente: o motorista" seria preencher a linha para não
        # dizer nada. Sem nome, a linha some.
        "Cliente": _nome_ou_vazio(s.dados.get("interlocutor", "")),
        "Número": s.telefone.replace("whatsapp:", ""),
        # ⚠️ Saem da **sessão**, não de `dados["posição"]`, desde 03/09/2026.
        # `dados` guarda o que foi para o prompt, e ali a posição vinha da fonte
        # de rastreamento. `s.endereco` e `s.latitude/longitude` são o que o
        # evento trouxe: é a posição de onde a coisa aconteceu.
        "Logradouro": s.endereco or "",
        "Coordenada": _coordenada(s),
        "Triagem": (
            f"{s.probabilidade_real}% de chance de ser real"
            if s.probabilidade_real is not None
            else ""
        ),
        # ⚠️ Antes a ficha mostrava o custo e escondia quem gastou. Com a
        # Central podendo trocar o cérebro, "qual modelo atendeu este caso?" é a
        # primeira pergunta de qualquer comparação, e a resposta estava só no
        # span de tracing.
        # ⚠️ **A linha que faltava para a aba de supressão temporária.**
        #
        # O cartão de lá abre esta ficha desde 03/09/2026, e sem isto a
        # ocorrência não dizia a única coisa que aquela aba existe para
        # informar: até quando os alarmes estão desligados.
        #
        # Encerrado quer dizer *acabou*; suprimido quer dizer *continua
        # acontecendo e é esperado*. Sem o prazo à vista, os dois parecem a
        # mesma coisa na tela.
        "Alarmes suprimidos": _supressao(s),
        "IA": s.modelo or "",
        "Custo desta ocorrência": f"US$ {s.custo_usd:.4f}",
        "Origem": "disparo de teste pela Central" if s.origem == "teste" else "",
    }
    return {rotulo: valor for rotulo, valor in campos.items() if valor}


def _ocorrencia_da_sessao(s: Sessao) -> Ocorrencia:
    """O registro completo de uma conversa que aconteceu num celular de verdade."""
    if s.desfecho:
        estado = f"Encerrada pela IA · {s.desfecho}"
        # ⛔ **Vazio desde 03/09/2026, a pedido do Leonardo.** Eram "Reabrir a
        # ocorrência", "Ligar para o interlocutor" e "Marcar para revisão".
        #
        # Nenhum dos três existia: o painel renderiza `acoes` como `<button>`
        # **sem `onClick`**, então eram três botões que aceitavam o clique e não
        # faziam nada. Num caso já encerrado isso é pior que enfeite: quem
        # apertasse "Reabrir a ocorrência" iria embora achando que reabriu.
        #
        # Voltam quando existir a ação por trás, uma a uma, não como conjunto.
        acoes: list[str] = []
    elif s.escalada:
        estado = f"Aguardando operador · {s.motivo_encerramento}"
        acoes = []
    else:
        estado = "Em atendimento pela IA"
        acoes = []

    ultima_da_ia = next((f.texto for f in reversed(s.falas) if f.quem == "ia"), "")

    return Ocorrencia(
        ocorrencia_id=s.ocorrencia_id,
        tipo_evento=s.tipo.rotulo,
        grau=s.grau,  # type: ignore[arg-type]
        canal=s.canal,  # type: ignore[arg-type]
        placa=s.dados.get("placa", "—"),
        interlocutor=s.dados.get("interlocutor", "cliente"),
        telefone=s.telefone.replace("whatsapp:", ""),
        aberta_ha=f"{s.criada_em.astimezone(FUSO_PAINEL):%d/%m/%Y às %H:%M}",
        latitude=s.latitude,
        longitude=s.longitude,
        endereco=s.endereco,
        briefing=ultima_da_ia or "A IA ainda não falou nesta ocorrência.",
        handoff=s.handoff,
        probabilidade_real=s.probabilidade_real,
        acoes=acoes,
        conversa=[
            Turno(
                quem=f.quem,  # type: ignore[arg-type]
                fala=f.texto,
                horario=f"{f.momento.astimezone(FUSO_PAINEL):%H:%M}",
                tipo=f.tipo or ("audio" if f.audio else "texto"),  # type: ignore[arg-type]
                duracao_s=int(f.duracao_s) if f.duracao_s else None,
                transcrito=f.transcrito,
                botoes=f.botoes,
                status="lido" if f.quem == "ia" else None,
            )
            for f in s.falas
        ],
        turnos=len(s.falas),
        duracao=s.duracao,
        ficha=_ficha_da_sessao(s, estado),
        auditoria=[
            EventoAuditoria(
                horario=f"{p.momento.astimezone(FUSO_PAINEL):%H:%M:%S}",
                descricao=f"<b>{p.ator}</b> · {p.descricao}",
            )
            for p in s.trilha
        ],
        politica_versao=POLITICA_VERSAO,
        prompt_versao=versao_dos_prompts(),
    )


def _como_ocorrencia(resultado: Resultado) -> Ocorrencia:
    grau = {"CRITICA": "critica", "ALTA": "alta", "MEDIA": "media", "BAIXA": "baixa"}[
        resultado.criticidade
    ]

    # ⛔ Vazio pelo mesmo motivo do `_ocorrencia_da_sessao`: eram botões sem
    # `onClick`. Ver o comentário longo lá.
    acoes: list[str] = []

    return Ocorrencia(
        ocorrencia_id=resultado.ocorrencia_id,
        tipo_evento=resultado.tipo_evento,
        grau=grau,  # type: ignore[arg-type]
        canal=resultado.canal or "LIGACAO",  # type: ignore[arg-type]
        placa=resultado.ocorrencia_id.split("-")[-1],
        interlocutor="simulação",
        aberta_ha="agora",
        latitude=resultado.latitude,
        longitude=resultado.longitude,
        endereco=resultado.endereco,
        briefing=resultado.briefing,
        handoff=resultado.handoff,
        probabilidade_real=resultado.probabilidade_real,
        acoes=acoes,
        conversa=[
            Turno(quem=t.quem, fala=t.fala) for t in resultado.conversa  # type: ignore[arg-type]
        ],
        turnos=len(resultado.conversa),
        duracao="—",
        ficha={
            "Estado": (
                "Encerrada pela IA"
                if resultado.estado == "ENCERRADA_PELA_IA"
                else "Aguardando operador"
            ),
            "Elegível para a IA": "sim" if resultado.elegivel_ia else "não",
            "Motivo": resultado.motivo_inelegibilidade or "—",
            "Desfecho": resultado.desfecho or "—",
            "Briefing escrito pela IA": "sim" if resultado.briefing_gerado_por_ia else "não",
            "Custo desta ocorrência": f"US$ {resultado.custo_usd:.4f}",
        },
        auditoria=[
            EventoAuditoria(
                horario=f"{p.momento:%H:%M:%S}",
                descricao=f"<b>{p.ator}</b> · {p.acao} — {p.detalhe}",
            )
            for p in resultado.auditoria
        ],
        politica_versao=resultado.politica_versao,
        prompt_versao=resultado.prompt_versao,
    )


def _encerradas_simuladas() -> list[Encerrada]:
    """As simulações desta sessão que a IA fechou sozinha.

    Uma função só, usada pela aba Encerrados **e** pelo vital da Visão Geral —
    senão as duas telas contam coisas diferentes e o número perde o sentido.
    """
    encerradas = []
    for r in _SIMULADAS:
        if r.estado != "ENCERRADA_PELA_IA":
            continue
        fim = r.auditoria[-1].momento.astimezone(FUSO_PAINEL) if r.auditoria else None
        encerradas.append(
            Encerrada(
                ocorrencia_id=r.ocorrencia_id,
                tipo_evento=r.tipo_evento,
                canal=r.canal or "LIGACAO",  # type: ignore[arg-type]
                placa=r.ocorrencia_id.split("-")[-1],
                interlocutor="simulação",
                desfecho=r.desfecho or "—",
                encerrada_por="ia",
                responsavel="IA",
                encerrada_em=f"{fim:%H:%M}" if fim else "—",
                encerrada_dia=f"{fim:%d/%m/%Y}" if fim else None,
                duracao="—",
                custo_usd=round(r.custo_usd, 6),
                tem_detalhe=True,
            )
        )
    return encerradas


@router.get(
    "/encerrados",
    response_model=Encerrados,
    summary="Ocorrências já resolvidas, pela IA ou pelo operador",
)
async def obter_encerrados() -> Encerrados:
    """As simulações encerradas pela IA entram no topo, junto das de amostra.

    O operador precisa ver o que a IA fechou sozinha — e não apenas o que
    sobrou para ele. Contenção que ninguém consegue conferir não é métrica,
    é alegação.
    """
    base = amostra.encerrados()
    das_simulacoes = _encerradas_simuladas()

    # Conversas de WhatsApp que a IA fechou sozinha, com desfecho aprovado pela
    # política. As que ela escalou não entram aqui — elas foram para a fila
    # humana e ainda não têm desfecho.
    do_whatsapp = [
        Encerrada(
            ocorrencia_id=s.ocorrencia_id,
            tipo_evento=s.tipo.rotulo,
            canal="TEXTO",
            placa=s.dados.get("placa", "—"),
            interlocutor=f"{s.dados.get('interlocutor', 'cliente')} · WhatsApp real",
            desfecho=s.desfecho or "—",
            encerrada_por="ia",
            responsavel="IA",
            encerrada_em=f"{s.ultima_em.astimezone(FUSO_PAINEL):%H:%M}",
            encerrada_dia=f"{s.ultima_em.astimezone(FUSO_PAINEL):%d/%m/%Y}",
            duracao=s.duracao,
            custo_usd=round(s.custo_usd, 6),
            tem_detalhe=True,
        )
        for s in SESSOES.todas()
        if s.desfecho
    ]

    da_ia = das_simulacoes + do_whatsapp

    # ⚠️ **A lista mostra só o que a IA fechou sozinha, desde 03/09/2026.**
    #
    # Antes vinham juntos os casos que uma pessoa encerrou, e Leonardo apontou o
    # problema: *"deixe nos encerrados somente aqueles eventos que a IA entendeu
    # tudo e conseguiu tratar sozinha"*. Um caso que escalou e foi resolvido no
    # telefone não é contenção da IA, e esta aba existe para medir contenção.
    #
    # ⛔ **Os totais continuam contando os dois, e isso não é inconsistência.**
    # A contenção do turno é uma **razão**: sem o denominador ela não existe.
    # Filtrar os dois lugares faria `total_operador` virar zero e o cabeçalho
    # anunciar "100% de contenção" — inflando exatamente o número que a mudança
    # queria proteger. A lista responde "o que a IA resolveu"; os números
    # respondem "de quanto".
    encerradas_pela_ia = [e for e in base.itens if e.encerrada_por == "ia"]
    return Encerrados(
        itens=da_ia + encerradas_pela_ia,
        total_ia=base.total_ia + len(da_ia),
        total_operador=base.total_operador,
    )


class NumeroRemovido(BaseModel):
    """Um número que pediu para não receber mais os avisos de um veículo."""

    telefone: str
    placa: str
    quando: str
    ocorrencia_id: str
    pedido: str = Field(description="A frase do cliente, para o operador julgar.")


@router.get(
    "/numeros-removidos",
    response_model=list[NumeroRemovido],
    summary="Números que pediram para sair dos avisos de um veículo",
    description=(
        "Linha de celular cancelada é reciclada pela operadora, e o cadastro da "
        "Bahrd continua apontando para ela: quem atende passa a receber alarme de "
        "um caminhão que nunca foi seu. Parar de mandar depois do pedido é "
        "**obrigação de plataforma** — ignorar derruba a nota de qualidade do "
        "número na Meta.\n\n"
        "⚠️ **Não é a aba «Desativados».** Lá é o veículo com alarme suprimido "
        "por um tempo, a pedido do dono. Aqui é o contato que saiu, e o alarme "
        "continua valendo para quem mais estiver no cadastro.\n\n"
        "**O que o operador faz com esta lista:** pedir à Bahrd a correção do "
        "telefone no cadastro. O bloqueio é remendo nosso; a correção é lá."
    ),
)
async def obter_numeros_removidos() -> list[NumeroRemovido]:
    return [
        NumeroRemovido(
            telefone=i.telefone,
            placa=i.placa,
            quando=f"{i.quando.astimezone(FUSO_PAINEL):%d/%m %H:%M}",
            ocorrencia_id=i.ocorrencia_id,
            pedido=i.pedido,
        )
        for i in await numeros_removidos.listar(settings())
    ]


@router.delete(
    "/numeros-removidos/{placa}",
    summary="Devolve um número aos avisos de um veículo",
    description=(
        "⛔ **Existe porque a IA pode errar.** Ela interpreta linguagem, e um "
        "«não é meu carro» dito por confusão vira bloqueio. Sem desfazer pelo "
        "painel, a correção exigiria alguém com acesso ao Redis — e quem "
        "percebe o engano é justamente quem não tem."
    ),
)
async def devolver_numero(placa: str, telefone: str) -> dict[str, bool]:
    return {"devolvido": await numeros_removidos.devolver(settings(), telefone, placa)}


class Desativado(BaseModel):
    """Veículo com alarmes suprimidos por um período."""

    ocorrencia_id: str
    tipo_evento: str
    placa: str
    interlocutor: str
    desfecho: str
    desativado_em: str
    ate: str = Field(description="Hora do fim, ou 'até a situação mudar'.")
    expirado: bool = Field(description="O prazo já passou e ninguém reativou.")


@router.get(
    "/desativados",
    response_model=list[Desativado],
    summary="Veículos com alarmes suprimidos temporariamente",
    description=(
        "Vem dos scripts reais da Central: quando o cliente confirma manutenção "
        "ou transporte, o operador não encerra o assunto — ele **desconsidera os "
        "eventos enquanto a situação durar**. Tratar isso como encerramento faz "
        "o mesmo veículo disparar de novo em minutos. Ver `docs/23`."
    ),
)
async def obter_desativados() -> list[Desativado]:
    itens: list[Desativado] = []
    for s in SESSOES.todas():
        if not s.desativada:
            continue
        itens.append(
            Desativado(
                ocorrencia_id=s.ocorrencia_id,
                tipo_evento=s.tipo.rotulo,
                placa=s.dados.get("placa", "—"),
                interlocutor=s.dados.get("interlocutor", "cliente"),
                desfecho=s.desfecho or "—",
                desativado_em=f"{s.ultima_em.astimezone(FUSO_PAINEL):%H:%M}",
                # Sem prazo é o caso de manutenção e base do cliente: sai quando
                # o veículo voltar a se mover, não quando o relógio bate.
                ate=(
                    f"{s.desativada_ate.astimezone(FUSO_PAINEL):%H:%M}"
                    if s.desativada_ate
                    else "até a situação mudar"
                ),
                expirado=s.desativacao_expirou,
            )
        )
    return itens


@router.get(
    "/reincidencia",
    response_model=list[EquipamentoReincidente],
    summary="Equipamentos que repetem o mesmo evento — candidatos a inspeção",
    description=(
        "Aritmética sobre o desfecho que o operador registrou, sem modelo no "
        "caminho. Um equipamento que dispara o mesmo evento repetidas vezes e "
        "nunca tem causa real é problema de manutenção, não de central — e "
        "resolver na origem é mais barato que atender bem (doc 01 §4.3). "
        "Hoje lê da amostra; passa a ler do sistema da Bahrd quando houver acesso."
    ),
)
async def obter_reincidencia() -> list[EquipamentoReincidente]:
    return amostra.reincidencia()


@router.get(
    "/metricas",
    response_model=Metricas,
    summary="Métricas de supervisão (contenção, latência, volume, escalonamentos)",
)
async def obter_metricas() -> Metricas:
    """Em produção esta rota fica restrita ao perfil de supervisor — o operador
    não vê números agregados enquanto atende."""
    m = amostra.metricas()

    # O vital tem de contar o mesmo que a aba Encerrados lista, incluindo o que
    # foi simulado nesta sessão. Dois números diferentes para a mesma coisa em
    # duas telas é como se perde a confiança no painel inteiro.
    if simuladas := len(_encerradas_simuladas()):
        base = amostra.encerrados()
        total_ia = base.total_ia + simuladas
        for vital in m.vitais:
            if vital.rotulo == "Encerradas":
                vital.valor = str(total_ia + base.total_operador)
                vital.nota = f"{total_ia} pela IA · {base.total_operador} pelo operador"

    return m


@router.get("/estado", summary="Estado operacional da IA para o cabeçalho do painel")
async def obter_estado() -> dict[str, object]:
    cfg = settings()
    return {
        "ia_ativa": not cfg.kill_switch_ativo,
        "modo_voz": cfg.modo_voz,
        "ambiente": cfg.app_env,
        "panico_autonomo": cfg.panico_autonomo,
        "fonte_rastreamento": cfg.fonte_rastreamento,
    }


class PedidoSimulacao(BaseModel):
    codigo_evento: str = Field(
        default="PANICO", description="Código do catálogo em `domain/eventos.py`."
    )
    imei: str = Field(
        default="XYZ4E56",
        description="Identifica qual contexto a fonte de amostra devolve. "
        "`XYZ4E56` traz sinais de acionamento acidental; `RST7U88` traz "
        "desvio de rota e jammer na janela.",
    )


@router.post(
    "/simular",
    summary="Injeta um evento e roda o pipeline completo",
    description=(
        "Publica um evento como se viesse do sistema da Bahrd e executa o "
        "caminho inteiro: política, consulta de contexto, triagem ou "
        "atendimento, e registro. Existe enquanto o webhook não chega — o "
        "caminho depois da injeção é o mesmo que o webhook vai usar."
    ),
)
async def simular(pedido: PedidoSimulacao) -> dict[str, object]:
    cfg = settings()
    llm = construir_cliente_llm(cfg)
    try:
        pipeline = Pipeline(cfg, llm, construir_fonte(cfg))
        ocorrencia_id = (
            f"OC-{datetime.now(UTC):%Y-%m-%d}-{uuid.uuid4().hex[:4].upper()}-{pedido.imei}"
        )
        resultado = await pipeline.processar(ocorrencia_id, pedido.codigo_evento, pedido.imei)
    finally:
        await llm.fechar()

    _SIMULADAS.insert(0, resultado)
    del _SIMULADAS[12:]

    return {
        "ocorrencia_id": resultado.ocorrencia_id,
        "estado": resultado.estado,
        "elegivel_ia": resultado.elegivel_ia,
        "desfecho": resultado.desfecho,
        "custo_usd": round(resultado.custo_usd, 6),
        "passos": len(resultado.auditoria),
    }
