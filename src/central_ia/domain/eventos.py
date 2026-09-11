"""Catálogo de tipos de evento em escopo — **fonte única da verdade**.

Os rótulos são os **do sistema da Bahrd**, escritos como aparecem lá. Isso é
deliberado: quando um operador ou o time da Bahrd olhar a tela, o nome tem de
ser o mesmo que ele já conhece, sem tradução mental. O `codigo` é nosso e
estável; o `rotulo` é deles e pode mudar.

Três estados, e eles são diferentes:

* **elegível** — há playbook escrito e política liberando; a IA conduz.
* **em escopo, inelegível** — o evento entra na fila do operador e a IA não
  fala com ninguém. Pânico e roubo ativo são assim por natureza; os demais são
  assim porque ainda falta playbook ou falta informação da Bahrd.
* **fora do catálogo** — a IA não toca, e `elegivel_para_ia` devolve `False`.

Confundir "inelegível" com "fora de escopo" é como um evento crítico vira
silêncio, por isso os dois existem separados.

**A IA nunca decide a própria elegibilidade** (princípio 1). Este catálogo é
determinístico e versionado; o motor de políticas (Sprint 1) lê da tabela
`politica_evento`, semeada por `migrations/oracle/004_politica_evento_v1_1.sql`
com exatamente estes valores.

⚠️ Campos `confirmar_com_a_link` marcam o que foi **inferido** e precisa de
confirmação. Estão em código, e não num documento, para não se perderem.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Literal

Criticidade = Literal["BAIXA", "MEDIA", "ALTA", "CRITICA"]
Canal = Literal["LIGACAO", "AUDIO", "TEXTO"]

#: Versão da política. Vai junto com cada decisão na trilha de auditoria.
#:
#: **v2.0 muda comportamento, não só dados.** Até a v1.1 os eventos críticos
#: nunca chegavam à IA — a barreira era o *tipo* do evento. Na v2.0 a barreira
#: passa a ser a *evidência*: a IA triagem antes de qualquer contato e devolve
#: uma probabilidade de o caso ser real. Acima do limiar, o caso é do humano,
#: com o histórico do que a IA já apurou junto.
POLITICA_VERSAO = "v2.0"

#: Acima disto, o caso vai para o humano sem a IA falar com ninguém.
#:
#: O número é da operação, não do código: é onde a Bahrd decide trocar contenção
#: por segurança. Fica aqui, e não dentro do prompt, porque mudar um limiar não
#: pode depender de reescrever instrução de modelo — e porque assim ele aparece
#: na trilha de auditoria de toda decisão que ele produziu.
LIMIAR_ESCALONAMENTO = 90

#: Um dia, em segundos — o padrão de espera por quem não respondeu.
#:
#: É a janela de atendimento da Meta, e por isso é o teto natural: passada ela,
#: a conversa recomeça de qualquer jeito, com template novo e cobrança nova.
#: Esperar além disso seria manter aberto um atendimento que já não pode
#: continuar.
UM_DIA_S = 24 * 60 * 60

#: Abaixo disto, e só com confiança alta, a IA pode encerrar sozinha.
#:
#: A triagem passa a decidir nas duas direções, em três faixas:
#:
#:     ≥ 90        →  humano assume, sem nenhum contato automático
#:     21 a 89     →  a IA atende, mas o fechamento passa pelo operador
#:     ≤ 20        →  a IA atende e encerra sozinha
#:
#: A faixa do meio não é indecisão: é onde a evidência não é forte o bastante
#: nem para largar o caso nem para fechá-lo. Sem ela, todo caso duvidoso cairia
#: para um dos dois lados por arredondamento.
LIMIAR_ENCERRAMENTO_AUTONOMO = 20


@dataclass(frozen=True)
class TipoEvento:
    codigo: str
    #: Rótulo exato do sistema da Bahrd.
    rotulo: str
    criticidade: Criticidade

    #: A IA pode conduzir o atendimento? `False` significa humano exclusivo.
    elegivel_ia: bool

    #: A IA precisa **classificar antes de falar**?
    #:
    #: Separado de `elegivel_ia` de propósito. Elegibilidade responde "a IA pode
    #: tratar?"; isto responde "ela pode abrir a boca antes de olhar os dados?".
    #: Num pânico as duas coisas são diferentes: a IA trata, mas só depois de
    #: cruzar telemetria e histórico — ligar às cegas para quem pode estar num
    #: assalto é o erro que nenhum roteiro conserta depois.
    exige_triagem_previa: bool = False

    #: Segundos até o escalonamento obrigatório (ou SLA humano, se inelegível).
    janela_s: int = 60

    #: Quanto a IA espera a cada vez que a pessoa diz "vou verificar".
    #:
    #: Uma entrada por espera, **em ordem decrescente**: `(120, 60)` quer dizer
    #: dois minutos na primeira pausa, um na segunda, e humano na terceira. A
    #: quantidade de entradas É o teto de retomadas — não existe um segundo
    #: campo para desalinhar com este.
    #:
    #: Decrescente de propósito. A primeira pausa é alguém indo verificar; a
    #: segunda já é sinal de que a coisa não vai se resolver rápido, e insistir
    #: com o mesmo intervalo é a central esperando por esperar.
    #:
    #: Tupla vazia desliga a espera. Não confundir com `janela_s`: aquela é o
    #: prazo até o caso ser do humano; esta é quanto tempo a IA aguenta calada
    #: dentro de uma conversa viva.
    esperas_s: tuple[int, ...] = ()

    #: Segundos de silêncio **antes da primeira resposta** que levam o caso ao
    #: humano. Zero desliga, e é o padrão.
    #:
    #: **Por que não é o `janela_s`.** Aquele foi pensado para um pânico que
    #: tenta ligação primeiro (`cascata_canais`), e ali 30 s de silêncio
    #: significam alguma coisa: o telefone tocou e ninguém atendeu. No WhatsApp
    #: não significam nada — o celular pode estar no bolso, no suporte, no
    #: silencioso. Era o mesmo número medindo duas coisas diferentes.
    #:
    #: **Por que não é o `esperas_s`.** Aquele conta o silêncio *dentro* de uma
    #: conversa viva, depois de a pessoa ter dito "peraí". Este conta o silêncio
    #: de quem nunca falou — e até 25/08/2026 ninguém contava: a notificação
    #: saía, o motorista não respondia, e a ocorrência expirava sem desfecho,
    #: sem operador e sem ninguém saber. Inclusive num pânico.
    #:
    #: Nos eventos comuns o valor é a própria janela da Meta: um gestor pode
    #: estar em reunião, e remoção de bateria não é urgência. Passado o dia, o
    #: caso encerra com o desfecho do catálogo — **encerra**, não desaparece.
    silencio_no_texto_s: int = UM_DIA_S

    #: Segundos de silêncio **no meio da conversa, sem a pessoa ter avisado**.
    #:
    #: A terceira e última forma de silêncio, e a que ficou sem dono até
    #: 25/08/2026. As outras duas são `silencio_no_texto_s` (quem nunca falou) e
    #: `esperas_s` (quem disse "peraí"). Esta é a de quem estava conversando,
    #: recebeu uma pergunta e nunca mais respondeu — e é, de longe, a mais
    #: comum: gente que lê, se distrai e não volta.
    #:
    #: Ficava sem tratamento porque o relógio da retomada só liga quando o
    #: modelo marca `[AGUARDAR]`, e ele só marca quando a pessoa **anuncia** a
    #: pausa. Sem anúncio, nenhum relógio existia: a ocorrência travava naquele
    #: ponto e sumia do painel um dia depois, sem desfecho.
    #:
    #: No pânico é mais curto que a espera anunciada não seria — é a mesma. Quem
    #: apertou o botão e para de responder é o mesmo sinal, tenha avisado ou
    #: não.
    silencio_sem_aviso_s: int = UM_DIA_S

    #: Ao vencer o `silencio_sem_aviso_s`, a IA **pergunta de novo** em vez de
    #: encerrar calada?
    #:
    #: ⚠️ **Levantado num teste real de 01/09/2026, com duas conversas no mesmo
    #: número.** Uma fechou; a outra parou exatamente na pergunta que decide
    #: tudo — *"posso deixar os avisos desconsiderados enquanto ele estiver no
    #: local?"* — e o sistema simplesmente esperou 24 h para encerrar sem
    #: desfecho. A pergunta mais importante do playbook era a que mais ficava
    #: sem resposta, e ninguém insistia.
    #:
    #: A máquina de retomada já existia e resolvia isso, mas só era alcançada
    #: quando o modelo marcava `[AGUARDAR]`, e ele só marca quando a pessoa
    #: **anuncia** a pausa. Quem lê e se distrai não anuncia nada.
    #:
    #: ⚠️ **Falso por padrão, e o pânico tem de continuar falso.** Se o botão
    #: foi apertado de verdade, escrever qualquer coisa avisa quem estiver do
    #: lado do motorista que a central percebeu — o `PB-PANICO` proíbe, e o
    #: `_vigiar_silencio` foi escrito justamente para não falar.
    #:
    #: Quando acaba a última retomada, encerra como sempre encerrou.
    retoma_no_silencio: bool = False

    #: Pode ser encerrado quando não há operador para receber o escalonamento?
    #:
    #: ⚠️ **`False` no pânico, e é a correção de 02/09/2026.** Sem operador, o
    #: `_encaminhar` encerrava o caso registrando o motivo pelo qual ele teria
    #: ido para uma pessoa. Para quase todo evento isso é razoável: o desfecho
    #: gravado é o próprio motivo, e quem lê a lista de encerrados vê o porquê.
    #:
    #: **No pânico não é.** O caso sai da fila "precisa de você" e vai para os
    #: encerrados, onde ninguém volta a olhar. Um acionamento que a triagem
    #: julgou provavelmente real desaparecia da tela sem nenhuma pessoa ter
    #: visto. Leonardo, 02/09/2026: *"fechou sozinho, não pode acontecer isso"*.
    #:
    #: `ESCALONAMENTO_HUMANO_ATIVO` existe porque não há operador para receber.
    #: Mas **o painel é como uma pessoa recebe** — deixar aberto ali não depende
    #: de plantão nenhum, e é o comportamento certo dos dois lados da chave.
    encerra_sem_operador: bool = True

    @property
    def retomadas_maximas(self) -> int:
        return len(self.esperas_s)

    def espera_da_retomada(self, ja_feitas: int) -> int:
        """Quanto esperar antes da retomada de número `ja_feitas + 1`."""
        if ja_feitas >= len(self.esperas_s):
            return 0
        return self.esperas_s[ja_feitas]

    #: Ordem de canais que a IA tenta. Vazio quando ela não fala.
    cascata_canais: tuple[Canal, ...] = ()

    playbook: str | None = None

    #: Lista branca. A IA não pode fechar com nada fora daqui.
    desfechos_permitidos: tuple[str, ...] = ()

    #: Com que desfecho fechar quando a pessoa **não respondeu** até o fim.
    #:
    #: `None` significa que sem contato o caso é do operador. Preenchido
    #: significa que o silêncio, naquele tipo de evento, já é um desfecho
    #: legítimo — a orientação foi entregue e o risco não exige confirmação.
    #:
    #: A fronteira é essa e não é negociável no prompt: silêncio numa remoção
    #: de bateria ou num movimento sem ignição é a assinatura de um roubo, e
    #: fechar ali seria fechamento falso, não contenção. Nos eventos de
    #: velocidade é o oposto — o motorista está dirigindo, muitas vezes não
    #: responde, e insistir só produz alerta ignorado.
    desfecho_sem_contato: str | None = None

    #: Por que é inelegível — vai para a trilha de auditoria e para a tela.
    motivo_inelegibilidade: str | None = None

    observacao: str = ""
    requer_confirmacao_dupla: bool = False
    modo_paralelo: bool = False
    contatos: tuple[str, ...] = field(default=())

    #: Pergunta em aberto para a Bahrd. Enquanto existir, o evento não é elegível.
    confirmar_com_a_link: str | None = None

    #: Eventos que descrevem o MESMO fato operacional e não podem gerar dois
    #: contatos com a mesma pessoa no mesmo turno.
    grupo_deduplicacao: str | None = None


# ═══════════════════════════ Elegíveis — têm playbook ═══════════════════════

REMOCAO_BATERIA = TipoEvento(
    codigo="REMOCAO_BATERIA",
    rotulo="Remoção de bateria",
    criticidade="ALTA",
    elegivel_ia=True,
    # 90 s porque o rastreador passa a funcionar com bateria reserva, que dura
    # pouco. Passando disso, o caminhão pode ficar sem rastreio.
    janela_s=90,
    # Esperar num evento de janela de 90 s parece contradição, e não é: este
    # playbook roda em `modo_paralelo`, com um operador já de posse do caso. A
    # IA esperando não deixa ninguém desassistido — ela só evita entregar de
    # volta um caso que ia se resolver sozinho.
    #
    # ⏱ Encurtado para a demonstração (era 120+60). Numa apresentação, dois
    # minutos de silêncio na frente de uma sala é uma eternidade. O valor de
    # operação real precisa ser combinado com a Bahrd — provavelmente maior que
    # este, porque um motorista descendo do caminhão demora mais que um minuto.
    esperas_s=(60, 30),
    # A IA insiste quando o silêncio cai na pergunta da autorização. Nas
    # outras perguntas o prazo segue o padrão e o caso encerra sozinho.
    retoma_no_silencio=True,
    cascata_canais=("LIGACAO", "AUDIO"),
    playbook="PB-BATERIA",
    desfechos_permitidos=(
        "chave_geral_desligada_pelo_motorista",
        # O par de recusa da chave geral, irmão do `veiculo_em_manutencao_com_avisos`.
        "chave_geral_com_avisos_mantidos",
        # O mesmo evento com uma diferença que vale para sempre: o cliente
        # autorizou a regra permanente. Desfecho separado porque é ele que
        # dispara a escrita no sistema da Bahrd, e escrita permanente não pode
        # depender de o modelo ter contado direito o que combinou.
        #
        # Em 28/08/2026 a IA encerrou como chave geral sem oferecer nada, e a
        # regra foi criada assim mesmo: o mapa de tratativas ligava o desfecho
        # comum à ação permanente. Separar os dois é o que impede isso.
        "chave_geral_com_regra_autorizada",
        "veiculo_em_manutencao",
        # ⚠️ **A manutenção confirmada e a supressão recusada.**
        #
        # Sem este desfecho a IA não tinha para onde ir quando o cliente diz
        # "prefiro continuar recebendo os avisos": em 28/08/2026 ela fechou com
        # `veiculo_em_manutencao` mesmo assim, e o mapa de tratativas pediu a
        # supressão que ele **acabara de recusar**. Silenciar o alarme de quem
        # pediu para continuar sendo avisado é o erro mais caro deste playbook.
        #
        # Mesma regra dos outros dois pares: o desfecho é que carrega a
        # autorização, e a ausência dela tem nome próprio.
        "veiculo_em_manutencao_com_avisos",
        "falha_de_instalacao_reportada",
        # Veio do fluxo da URA da Vetor, e é a causa que faltava: o veículo
        # está no pátio ou na base do cliente. Estacionar ali é rotina, e a
        # rotina dispara o evento — mesmo caminhão, mesmo lugar, toda noite.
        #
        # Sem este desfecho a IA não tinha como fechar um caso legítimo e caía
        # em "causa não confirmada", que é falso. A lista da Vetor vale porque
        # é operação real da Bahrd há anos; o **menu** deles a gente descarta,
        # a **cobertura de causas** a gente herda.
        "local_e_base_do_cliente",
        # ⚠️ **O par do `chave_geral_com_regra_autorizada`, e nasceu do mesmo
        # jeito: uma conversa que prometeu e não pediu nada.**
        #
        # Em 28/08/2026 a IA confirmou a base, perguntou se o cliente queria
        # parar de ser avisado ali, ouviu «pode deixar de avisar aqui sim» e
        # respondeu *"sem avisos por aqui daqui pra frente"*. Fechou com
        # `local_e_base_do_cliente`, que não gera tratativa nenhuma. A promessa
        # era permanente e não saiu pedido nenhum: o cliente receberia o mesmo
        # alerta na noite seguinte.
        #
        # Desfecho separado pela mesma razão de sempre: regra que vale para
        # sempre não pode depender de o modelo ter contado direito o que
        # combinou. É o desfecho que carrega a autorização.
        "base_com_regra_autorizada",
        # O ramo "Outro motivo" do fluxo dos gestores (doc 19), autorizado pelo
        # Leonardo em 27/08/2026.
        #
        # ⚠️ **Desfecho genérico é ralo por natureza**: tudo que não encaixa
        # nas causas acima passa a poder fechar por aqui, e a estatística de
        # contenção perde sentido se ele virar a maioria.
        #
        # Duas travas contra isso, e nenhuma é o prompt. A IA **tem** de
        # registrar o motivo em texto (`motivo_informado`), senão o caso não
        # fecha por este desfecho; e o painel mostra esses casos com o motivo
        # ao lado, para dar para ler a lista e perceber quando uma causa nova
        # apareceu tantas vezes que merece nome próprio.
        #
        # É o oposto de proibir: o ralo fica aberto e vira instrumento de
        # medida do que está faltando no catálogo.
        "outro_motivo_confirmado_pelo_cliente",
        # E o par de recusa do ramo genérico. Fecham a regra combinada em
        # 28/08/2026 com o Leonardo: **a IA sempre pergunta antes de suprimir**,
        # em todos os caminhos, e a resposta dele vira o nome do desfecho.
        #
        # Sem estes dois a pergunta seria teatro: um "não" não teria como ser
        # registrado, e o caso fecharia suprimindo assim mesmo.
        "outro_motivo_com_avisos_mantidos",
        "sem_resposta_apos_tentativas",
        # ⛔ **O número não é do cliente.** Uma linha cancelada é reciclada pela
        # operadora e o cadastro da Bahrd continua apontando para ela: quem atende
        # passa a receber alarme de um caminhão que nunca foi seu.
        #
        # Não é desfecho do evento — o alarme continua sem causa apurada, e o
        # veículo segue disparando para quem de fato o monitora. É desfecho do
        # CONTATO: este número, para esta placa, sai da lista.
        #
        # Serve os três eventos que notificam, porque a linha errada recebe os
        # três. Ver `orchestration/numeros_removidos.py`.
        "numero_removido_a_pedido",
    ),
    desfecho_sem_contato="sem_resposta_apos_tentativas",
    modo_paralelo=True,
    contatos=("MOTORISTA", "GESTOR"),
    observacao=(
        "Uma pergunta com as duas causas normais dentro dela. Sem insistência: "
        "um humano já está com o caso, então não há prêmio por resolver e há "
        "risco em demorar."
    ),
)

MOVIMENTO_SEM_IGNICAO = TipoEvento(
    codigo="MOVIMENTO_SEM_IGNICAO",
    # Mesma razão do REMOCAO_BATERIA.
    retoma_no_silencio=True,
    rotulo="Movimento com ignição desligada",
    criticidade="ALTA",
    elegivel_ia=True,
    janela_s=60,
    # ⏱ Encurtado para a demonstração (era 90+45). Ver a nota em REMOCAO_BATERIA.
    esperas_s=(60, 30),
    cascata_canais=("LIGACAO", "TEXTO"),
    playbook="PB-MOV-SEM-IGNICAO",
    desfechos_permitidos=(
        "reboque_autorizado",
        "transporte_em_prancha_ou_balsa",
        "falso_positivo_gps",
        "sem_resposta_apos_tentativas",
        # ⛔ **O número não é do cliente.** Uma linha cancelada é reciclada pela
        # operadora e o cadastro da Bahrd continua apontando para ela: quem atende
        # passa a receber alarme de um caminhão que nunca foi seu.
        #
        # Não é desfecho do evento — o alarme continua sem causa apurada, e o
        # veículo segue disparando para quem de fato o monitora. É desfecho do
        # CONTATO: este número, para esta placa, sai da lista.
        #
        # Serve os três eventos que notificam, porque a linha errada recebe os
        # três. Ver `orchestration/numeros_removidos.py`.
        "numero_removido_a_pedido",
    ),
    desfecho_sem_contato="sem_resposta_apos_tentativas",
    requer_confirmacao_dupla=True,
    modo_paralelo=True,
    contatos=("MOTORISTA", "GESTOR"),
    observacao=(
        "Único playbook com confirmação dupla: roubo por reboque é a técnica "
        "usada justamente para não disparar os alertas ligados à ignição, então "
        "a palavra do motorista sozinha não fecha o caso."
    ),
)

# Os três abaixo são rótulos diferentes para a MESMA conversa: o motorista
# passou do limite. Por isso compartilham `PB-VELOCIDADE` e o mesmo grupo de
# deduplicação — um único excesso pode disparar mais de um deles, e três
# contatos pelo mesmo fato destroem a credibilidade da central.
VELOCIDADE_EXCEDIDA = TipoEvento(
    codigo="VELOCIDADE_EXCEDIDA",
    rotulo="Velocidade excedida",
    criticidade="BAIXA",
    elegivel_ia=True,
    janela_s=180,
    # O maior dos três: risco baixo e o motorista está dirigindo, então a
    # resposta demora mesmo. Pressa aqui só produz alerta ignorado.
    esperas_s=(60, 30),
    desfecho_sem_contato="sem_resposta_orientacao_enviada",
    cascata_canais=("AUDIO", "LIGACAO"),
    playbook="PB-VELOCIDADE",
    desfechos_permitidos=(
        "justificado_pelo_motorista",
        "orientacao_registrada",
        "sem_resposta_orientacao_enviada",
        "problema_mecanico_reportado",
    ),
    contatos=("MOTORISTA",),
    grupo_deduplicacao="VELOCIDADE",
    observacao=(
        "Maior volume, menor risco. Tom de colega, não de fiscal: motorista "
        "repreendido por robô deixa de atender a central, e no dia do alerta "
        "grave isso custa caro."
    ),
    confirmar_com_a_link=(
        "Qual a diferença real entre 'Velocidade excedida', 'Ultrapassou limite "
        "de velocidade' e 'Velocidade excedida dentro da cerca polígono'? "
        "Origem diferente (rastreador × plataforma), limiar diferente, ou são "
        "redundantes? A resposta define se o grupo de deduplicação está certo."
    ),
)

ULTRAPASSOU_LIMITE_VELOCIDADE = TipoEvento(
    codigo="ULTRAPASSOU_LIMITE_VELOCIDADE",
    rotulo="Ultrapassou limite de velocidade",
    criticidade="BAIXA",
    elegivel_ia=True,
    janela_s=180,
    esperas_s=(60, 30),
    desfecho_sem_contato="sem_resposta_orientacao_enviada",
    cascata_canais=("AUDIO", "LIGACAO"),
    playbook="PB-VELOCIDADE",
    desfechos_permitidos=VELOCIDADE_EXCEDIDA.desfechos_permitidos,
    contatos=("MOTORISTA",),
    grupo_deduplicacao="VELOCIDADE",
    confirmar_com_a_link=VELOCIDADE_EXCEDIDA.confirmar_com_a_link,
)

VELOCIDADE_EXCEDIDA_CERCA_POLIGONO = TipoEvento(
    codigo="VELOCIDADE_EXCEDIDA_CERCA_POLIGONO",
    rotulo="Velocidade excedida dentro da cerca polígono",
    criticidade="MEDIA",
    elegivel_ia=True,
    janela_s=180,
    esperas_s=(60, 30),
    desfecho_sem_contato="sem_resposta_orientacao_enviada",
    cascata_canais=("AUDIO", "LIGACAO"),
    playbook="PB-VELOCIDADE",
    desfechos_permitidos=VELOCIDADE_EXCEDIDA.desfechos_permitidos,
    contatos=("MOTORISTA",),
    grupo_deduplicacao="VELOCIDADE",
    observacao=(
        "Criticidade um degrau acima dos outros dois: excesso dentro de área "
        "delimitada costuma ser pátio, cliente ou zona urbana, onde o limite "
        "existe por segurança de terceiros, não por norma de rodovia."
    ),
    confirmar_com_a_link=(
        "Confirmar se a criticidade MEDIA está certa — depende de as cercas "
        "polígono serem áreas de risco ou áreas autorizadas. "
        + (VELOCIDADE_EXCEDIDA.confirmar_com_a_link or "")
    ),
)

# ══════════════ Críticos — a IA trata, mas triagem antes de falar ═════════════
#
# Política v2.0. A barreira deixou de ser o tipo do evento e passou a ser a
# evidência: a IA classifica primeiro, e só conversa quando os dados dizem que
# o caso provavelmente não é real. Acima de LIMIAR_ESCALONAMENTO, o caso vai
# para o humano sem nenhum contato — com tudo o que a IA apurou junto.

PANICO = TipoEvento(
    codigo="PANICO",
    rotulo="Pânico",
    criticidade="CRITICA",
    elegivel_ia=True,
    exige_triagem_previa=True,
    # Revisado em 25/08/2026, de 30 s. O 30 foi escrito para o pânico que tenta
    # **ligação** primeiro, e ali o silêncio significa alguma coisa: o telefone
    # tocou e ninguém atendeu. Por WhatsApp não significa — o celular pode estar
    # no bolso. A janela subiu junto com a espera para as duas não se
    # contradizerem: o modelo lê este número no contexto de toda conversa.
    janela_s=150,
    # Uma única espera, e **dentro** da janela. Esperar além dela só seria
    # admissível em `modo_paralelo`, com um operador já de posse do caso — e o
    # pânico não roda assim. Num pânico, silêncio depois de "peraí" é justamente
    # o que não se pode deixar passar.
    esperas_s=(120,),
    # Cinco minutos para quem nunca respondeu; dois para quem estava
    # conversando e sumiu. Mais tolerante antes da primeira resposta de
    # propósito: até ali o silêncio é ambíguo, o celular pode nem ter sido
    # olhado. Depois que a pessoa provou que está lendo, sumir é sinal.
    silencio_no_texto_s=300,
    silencio_sem_aviso_s=120,
    cascata_canais=("LIGACAO", "TEXTO"),
    playbook="PB-PANICO",
    # ⚠️ Nunca encerra sozinho por falta de operador — fica em "precisa de você".
    encerra_sem_operador=False,
    desfechos_permitidos=(
        "acionamento_acidental_confirmado",
        "alarme_falso_confirmado_por_triagem",
        # ⛔ **O número não é do cliente.** Uma linha cancelada é reciclada pela
        # operadora e o cadastro da Bahrd continua apontando para ela: quem atende
        # passa a receber alarme de um caminhão que nunca foi seu.
        #
        # Não é desfecho do evento — o alarme continua sem causa apurada, e o
        # veículo segue disparando para quem de fato o monitora. É desfecho do
        # CONTATO: este número, para esta placa, sai da lista.
        #
        # Serve os três eventos que notificam, porque a linha errada recebe os
        # três. Ver `orchestration/numeros_removidos.py`.
        "numero_removido_a_pedido",
    ),
    contatos=("MOTORISTA", "GESTOR"),
    observacao=(
        "A IA nunca abre a conversa dizendo 'pânico'. Se o botão foi apertado de "
        "verdade, dizer isso em voz alta é justamente o que não se pode fazer — "
        "quem estiver ouvindo do outro lado passa a saber que a central percebeu."
    ),
)

ROUBO_ATIVO_MOVIMENTO = TipoEvento(
    codigo="ROUBO_ATIVO_MOVIMENTO",
    rotulo="ATENÇÃO: VEÍCULO COM ROUBO ATIVO SE MOVIMENTOU!",
    criticidade="CRITICA",
    elegivel_ia=True,
    exige_triagem_previa=True,
    janela_s=15,
    cascata_canais=("LIGACAO",),
    playbook="PB-PANICO",
    desfechos_permitidos=(),
    contatos=("GESTOR",),
    observacao=(
        "Elegível pela mesma regra dos outros, e na prática quase sempre humano: "
        "o veículo já está marcado como roubado, então a probabilidade de ser "
        "real entra alta na triagem e passa do limiar sozinha. Não precisa de "
        "exceção no código — a evidência resolve. `desfechos_permitidos` vazio "
        "fecha a porta de qualquer jeito: a IA não encerra este evento."
    ),
)

# ═══════ Em escopo, inelegíveis por ora — falta playbook ou informação ═══════

ERRO_BATERIA_BACKUP = TipoEvento(
    codigo="ERRO_BATERIA_BACKUP",
    rotulo="Erro na bateria backup",
    criticidade="MEDIA",
    elegivel_ia=False,
    janela_s=600,
    motivo_inelegibilidade="Sem playbook — evento técnico, provavelmente sem contato",
    observacao=(
        "Não é 'Remoção de bateria': aqui a bateria reserva DO RASTREADOR "
        "acusou falha. Ninguém no veículo fez nada, e provavelmente não há "
        "conversa a ter — o destino natural é uma ordem de manutenção do "
        "equipamento, não um contato com o motorista."
    ),
    confirmar_com_a_link=(
        "Hoje este evento gera contato com alguém, ou vira chamado de "
        "manutenção? Se for manutenção, ele sai da fila de atendimento e vira "
        "integração — mais barato que qualquer playbook."
    ),
)

ENTROU_NA_CERCA = TipoEvento(
    codigo="ENTROU_NA_CERCA",
    rotulo="Entrou na cerca",
    criticidade="MEDIA",
    elegivel_ia=False,
    janela_s=300,
    motivo_inelegibilidade="Sem playbook — significado depende do tipo de cerca",
    observacao=(
        "O mesmo evento significa coisas opostas conforme a cerca: entrar numa "
        "área autorizada (pátio do cliente, base) é rotina e talvez nem devesse "
        "gerar alerta; entrar numa área de risco é grave."
    ),
    confirmar_com_a_link=(
        "As cercas são de área AUTORIZADA ou de área de RISCO? Existe essa "
        "distinção no cadastro, ou o mesmo evento cobre as duas? Sem isso não "
        "há como escrever um playbook que não erre metade dos casos."
    ),
)

VOLTOU_CERCA_POLIGONO = TipoEvento(
    codigo="VOLTOU_CERCA_POLIGONO",
    rotulo="Voltou à Cerca de Polígono",
    criticidade="BAIXA",
    elegivel_ia=False,
    janela_s=600,
    motivo_inelegibilidade="Sem playbook — provável evento de normalização, sem contato",
    observacao=(
        "Isto é o encerramento de uma exceção anterior, não uma exceção nova. "
        "O caminho mais barato aqui não é atender melhor: é fechar "
        "automaticamente a ocorrência de saída que o originou (doc 01 §4.3 — "
        "evitar que o falso positivo aconteça)."
    ),
    confirmar_com_a_link=(
        "Este evento sempre corresponde a uma saída anterior? Se sim, ele deve "
        "ENCERRAR a ocorrência aberta, não criar uma nova — e some da fila."
    ),
)

ENTRADA_2_ACIONADA = TipoEvento(
    codigo="ENTRADA_2_ACIONADA",
    rotulo="Entrada 2 acionada",
    criticidade="ALTA",
    elegivel_ia=False,
    janela_s=60,
    motivo_inelegibilidade="Significado da entrada não mapeado — tratado como alto risco",
    observacao=(
        "Entrada digital genérica: o que ela significa depende de como o "
        "equipamento foi instalado naquele veículo. Pode ser botão de pânico, "
        "sensor de porta do baú, tomada de força, sirene. Enquanto não houver "
        "mapa por cliente/veículo, a criticidade é assumida ALTA — falhar para "
        "o lado seguro é o único jeito de não transformar um pânico em rotina."
    ),
    confirmar_com_a_link=(
        "Existe mapa de qual sensor está ligado na entrada 2, por cliente ou "
        "por veículo? Se o significado variar entre veículos, a política precisa "
        "ser por veículo, não por tipo de evento."
    ),
)


#: Ordem deliberada: elegíveis, críticos, e os que aguardam definição.
CATALOGO: tuple[TipoEvento, ...] = (
    REMOCAO_BATERIA,
    MOVIMENTO_SEM_IGNICAO,
    VELOCIDADE_EXCEDIDA,
    ULTRAPASSOU_LIMITE_VELOCIDADE,
    VELOCIDADE_EXCEDIDA_CERCA_POLIGONO,
    PANICO,
    ROUBO_ATIVO_MOVIMENTO,
    ENTRADA_2_ACIONADA,
    ERRO_BATERIA_BACKUP,
    ENTROU_NA_CERCA,
    VOLTOU_CERCA_POLIGONO,
)

_POR_CODIGO = {t.codigo: t for t in CATALOGO}
_POR_ROTULO = {t.rotulo: t for t in CATALOGO}


def por_codigo(codigo: str) -> TipoEvento | None:
    """Devolve o tipo, ou `None` se estiver fora do escopo da POC."""
    return _POR_CODIGO.get(codigo)


def por_rotulo(rotulo: str) -> TipoEvento | None:
    """Busca pelo rótulo do sistema da Bahrd, como chega no webhook."""
    return _POR_ROTULO.get(rotulo)


def em_escopo(codigo: str) -> bool:
    return codigo in _POR_CODIGO


def elegivel_para_ia(codigo: str) -> bool:
    """Fecha em `False` para o que não conhece.

    Um tipo de evento novo aparecendo no webhook do sistema da Bahrd não pode
    virar atendimento automático por omissão. Desconhecido vai para humano.
    """
    tipo = _POR_CODIGO.get(codigo)
    return bool(tipo and tipo.elegivel_ia)


def desfecho_permitido(codigo: str, desfecho: str) -> bool:
    """Lista branca por tipo de evento. Nada fora dela fecha ocorrência."""
    tipo = _POR_CODIGO.get(codigo)
    return bool(tipo and desfecho in tipo.desfechos_permitidos)


def mesmo_grupo_de_deduplicacao(codigo_a: str, codigo_b: str) -> bool:
    """Dois eventos descrevem o mesmo fato operacional?

    Usado pelo motor para não gerar dois contatos com a mesma pessoa pelo mesmo
    excesso de velocidade — a regra de fadiga de alerta do `PB-VELOCIDADE`.
    """
    a, b = _POR_CODIGO.get(codigo_a), _POR_CODIGO.get(codigo_b)
    return bool(a and b and a.grupo_deduplicacao and a.grupo_deduplicacao == b.grupo_deduplicacao)


def pendencias_com_a_link() -> tuple[tuple[str, str], ...]:
    """Perguntas em aberto, para o checklist e para a próxima conversa com a Bahrd."""
    return tuple(
        (t.rotulo, t.confirmar_com_a_link) for t in CATALOGO if t.confirmar_com_a_link
    )

# ═════════════════ desativação temporária ═════════════════
#
# Vem dos scripts reais da Central (doc 12). Quando o cliente confirma
# manutenção ou transporte, o operador **não encerra** — ele diz:
#
#     "Iremos desconsiderar os eventos enquanto no local."
#     "Iremos desconsiderar os eventos durante esse transporte."
#
# É outra coisa. Encerrar diz *o caso acabou*; desativar diz *a situação
# continua, e os próximos alarmes dela são esperados*. Tratar os dois como o
# mesmo desfecho faz o veículo disparar de novo em minutos e alguém atender a
# mesma coisa outra vez — que é o custo que a IA existe para eliminar.

#: Desfecho → por quanto tempo suprimir alarmes do mesmo veículo.
#:
#: `None` significa **até a situação mudar** — veículo parado na base ou em
#: manutenção não tem prazo, sai quando voltar a se mover.
#: Quanto tempo os alarmes de transporte ficam suprimidos quando a pessoa
#: **não** soube dizer a duração.
#:
#: ⭐ **Duas horas, e o número é do gestor da Central**, repassado em
#: 02/09/2026: *"para movimento com ignição desligada é inativado por 2 horas
#: quando não há a confirmação do cliente do tempo em que vai levar o
#: transporte. Caso o cliente dê um tempo, é inativado pelo tempo informado.
#: Mas padrão é 2 horas."*
#:
#: Era 1 hora aqui, herdada do texto do script do operador. O padrão da
#: operação é o dobro.
DESATIVACAO_PADRAO_DE_TRANSPORTE = timedelta(hours=2)

#: Teto para o prazo que o cliente informa.
#:
#: A sessão da Meta morre em 24 h de qualquer jeito, então suprimir além disso
#: é prometer o que a conversa não alcança. E protege do "pode deixar
#: desativado a semana toda", que ninguém na Central autorizaria.
DESATIVACAO_MAXIMA_INFORMADA = timedelta(hours=24)

DESATIVACAO_POR_DESFECHO: dict[str, timedelta | None] = {
    # Sem prazo informado, o padrão da Central. Com prazo, quem manda é ele —
    # ver `Sessao.encerrar`.
    "reboque_autorizado": DESATIVACAO_PADRAO_DE_TRANSPORTE,
    "transporte_em_prancha_ou_balsa": DESATIVACAO_PADRAO_DE_TRANSPORTE,
    # "enquanto no local" — sem prazo; termina quando o veículo sair de lá.
    "veiculo_em_manutencao": None,
    "local_e_base_do_cliente": None,
}

#: Quanto tempo de transporte a Central pede para ser avisada de novo.
#:
#: ⚠️ **Era 1 hora, do texto antigo do operador**: *"Se esse deslocamento
#: exceder 1 hora, por favor, avise a Central."* Ficou incoerente quando a
#: supressão subiu para 2 horas, porque a IA pediria aviso na metade de um
#: prazo que ela mesma acabou de combinar.
#:
#: ⭐ **Vale a palavra do gestor da Central**, 02/09/2026: o padrão é 2 horas.
#: Amarrado ao `DESATIVACAO_PADRAO_DE_TRANSPORTE` para os dois não voltarem a
#: divergir no próximo ajuste, que foi exatamente como esta divergência nasceu.
AVISO_DE_TRANSPORTE_LONGO = DESATIVACAO_PADRAO_DE_TRANSPORTE


def desativa_temporariamente(desfecho: str | None) -> bool:
    """Este desfecho suprime alarmes em vez de encerrar o assunto?"""
    return desfecho in DESATIVACAO_POR_DESFECHO


def duracao_da_desativacao(desfecho: str | None) -> timedelta | None:
    """Por quanto tempo suprimir. `None` = até a situação mudar."""
    return DESATIVACAO_POR_DESFECHO.get(desfecho or "")
