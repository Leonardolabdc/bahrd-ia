"""Conversas de WhatsApp em andamento, uma por número de celular.

O webhook é sem memória: cada mensagem chega sozinha. O estado que transforma
mensagens soltas num atendimento mora aqui.

**Em memória de propósito, e só nesta fase.** No Sprint 2 isto vira Redis, com
TTL e chave por ocorrência — o contrato de `Sessao` não muda, muda o depósito.
Enquanto for POC, reiniciar a API encerra as conversas em curso.

⚠️ **Isso pesa mais desde que `VALIDADE` virou 24 h.** Com 30 minutos, a janela
em que um restart destruía algo era estreita; com um dia, qualquer deploy no
meio da tarde apaga conversas que ainda estavam vivas de manhã. A memória
passou a ser o prazo mais curto dos dois, e é ela que manda agora — trocar o
depósito deixou de ser arrumação e virou o próximo problema de verdade.

Duas travas que não dependem de julgamento do modelo:

* **`MAX_TURNOS_IA`** — a IA fala no máximo N vezes. Passando disso, humano.
  Conversa que não fecha em poucos turnos não vai fechar.
* **`VALIDADE`** — sessão parada vira sessão morta. Sem isso, uma resposta que
  chega três dias depois entraria numa conversa que ninguém lembra.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from central_ia.agent import atendimento_real
from central_ia.domain import eventos
from central_ia.domain.eventos import LIMIAR_ESCALONAMENTO, TipoEvento
from central_ia.ports.llm import Mensagem

#: Turnos da IA numa mesma conversa. Os playbooks miram 3 a 5.
MAX_TURNOS_IA = 5

#: A janela de atendimento da Meta. Dentro dela, mensagem livre é entregue e
#: **não é cobrada**. Fora, só template entrega — e template custa por disparo.
JANELA_DE_ATENDIMENTO = timedelta(hours=24)

#: Sessão sem atividade por mais que isso deixa de aceitar resposta.
#:
#: **É a janela da Meta, e não um número escolhido à parte.** Era de 30 minutos,
#: e a conta que isso fazia era esta: depois do "fico no aguardo" a IA cutuca
#: duas vezes, 60 s e 30 s, e para. O motorista que desce, vai até a oficina,
#: confere a bateria e volta 40 minutos depois — que é o comportamento normal de
#: quem foi verificar — encontrava a conversa morta e recebia o menu de teste da
#: POC no lugar da continuação.
#:
#: Amarrar as duas põe o limite onde ele já existe por fora: enquanto a janela
#: está aberta, a resposta dele chega de graça e o atendimento continua; passada
#: ela, a Meta exige template novo e a conversa recomeça de qualquer jeito.
#: Escolher qualquer valor menor é inventar um segundo prazo, mais curto que o
#: real, e perder atendimento no intervalo entre os dois.
#:
#: O motivo original da trava continua de pé, e é por isso que ela não vira
#: infinito: uma resposta que chega três dias depois entraria numa conversa que
#: ninguém lembra.
VALIDADE = JANELA_DE_ATENDIMENTO


def _chave(telefone: str) -> str:
    """Chave canônica da sessão — as duas grafias do celular caem no mesmo lugar.

    **Por que isto existe.** O mesmo celular chega escrito de jeitos diferentes
    conforme quem fala:

        payload da Bahrd  →  +5541999999999   (com o nono dígito)
        Meta no webhook  →   554199999999    (sem o nono dígito)
        Twilio           →  whatsapp:+5541999999999

    Indexar pelo texto cru faz a resposta do motorista não encontrar a conversa
    que a IA abriu. E o sintoma engana: a pessoa responde, o sistema trata como
    conversa nova, e ela recebe o menu de ajuda no meio do atendimento — foi
    exatamente o que aconteceu no primeiro evento real, em 24/08/2026.

    A canonização é **sem o nono dígito**, de propósito: é a forma que a Meta
    usa, e é a que menos varia entre fornecedores. Número que não é celular
    brasileiro volta só com os dígitos, sem transformação.
    """
    digitos = "".join(c for c in telefone if c.isdigit())
    # 55 + DDD(2) + 9 dígitos começando em 9 → o nono é o índice 4.
    if len(digitos) == 13 and digitos.startswith("55") and digitos[4] == "9":
        return digitos[:4] + digitos[5:]
    return digitos


@dataclass
class Fala:
    quem: str
    texto: str
    momento: datetime = field(default_factory=lambda: datetime.now(UTC))

    #: Foi nota de voz, não texto digitado.
    audio: bool = False

    #: O texto veio de transcrição automática. O operador precisa saber: STT
    #: erra, e ele pode estar lendo algo que o motorista não disse.
    transcrito: bool = False
    duracao_s: float | None = None

    #: Como o painel deve exibir. `None` deixa o painel deduzir de `audio`, que
    #: é o comportamento de toda fala escrita pela IA na conversa.
    #:
    #: `"template"` existe para a **primeira** mensagem, a pré-aprovada pela
    #: Meta: na tela do operador ela ganha o selo que explica por que aquele
    #: texto é engessado e não parece a IA falando.
    tipo: str | None = None

    #: Os botões que a pessoa teve na tela. Um "não respondeu" muda de sentido
    #: quando os únicos botões levavam para a loja de aplicativos.
    botoes: list[str] = field(default_factory=list)


@dataclass
class PassoDaTrilha:
    momento: datetime
    ator: str
    descricao: str


@dataclass
class Sessao:
    ocorrencia_id: str
    telefone: str
    tipo: TipoEvento
    canal: str
    dados: dict[str, str] = field(default_factory=dict)

    #: De onde este caso veio: `link` (evento real) ou `teste` (a tela do painel).
    #:
    #: ⛔ **Sem isto a tela de teste vira fonte de incidente.** Um pânico
    #: disparado para experimentar fica na mesma fila, com a mesma cara, do
    #: pânico de um motorista — e alguém de plantão pode acionar apoio por causa
    #: de um teste. A marca é o que separa os dois na tela e o que permite tirar
    #: os testes da conta quando alguém for medir a taxa de resolução da IA.
    #:
    #: Nasce de quem provou identidade com o token do painel, nunca do corpo do
    #: evento: pôr uma marca de confiança dentro do payload assinado seria
    #: convidar a falsificação da marca.
    origem: str = "link"

    #: Qual cérebro atende esta conversa. `None` usa o padrão do `.env`.
    #:
    #: ⚠️ **Carimbado na abertura, e é isso que faz a troca ser segura.** Alguém
    #: da Central pode trocar o modelo quando as respostas ao cliente estiverem
    #: ruins, e a troca vale **da próxima conversa em diante**: quem já está
    #: falando com a IA termina no cérebro em que começou.
    #:
    #: Trocar no meio deixaria a conversa quimera, com a triagem decidida por um
    #: modelo e a condução por outro, sem nada registrando isso. E como
    #: `settings()` é uma instância única e mutável, mexer nela pegaria também as
    #: conversas de cliente real em andamento, no meio de um turno.
    modelo: str | None = None

    #: Onde o veículo estava quando o evento chegou. Alimenta o mini-mapa do
    #: painel — inclusive na tela ao vivo, que é onde alguém acompanha a
    #: conversa acontecendo e precisa ver o caminhão ao mesmo tempo.
    latitude: float | None = None
    longitude: float | None = None
    endereco: str | None = None
    historico: list[Mensagem] = field(default_factory=list)
    turnos_ia: int = 0
    custo_usd: float = 0.0
    encerrada: bool = False
    motivo_encerramento: str | None = None
    desfecho: str | None = None
    escalada: bool = False
    probabilidade_real: int | None = None

    #: A triagem autorizou fechamento sem operador? Guardado no momento da
    #: triagem, não recalculado depois: a decisão foi tomada com aqueles dados,
    #: e é assim que ela precisa aparecer na auditoria meses depois.
    triagem_autoriza_encerrar: bool = False

    #: A pessoa chegou a responder? Encerrar sozinha um caso em que ninguém
    #: falou é fechar por silêncio — e silêncio num pânico é informação, não
    #: ausência dela.
    houve_resposta: bool = False

    #: Quantas vezes a IA já retomou depois de esperar. O teto está no catálogo.
    retomadas: int = 0

    #: A IA está esperando a pessoa voltar? Enquanto for `True`, um novo
    #: disparo do relógio não deve criar uma segunda espera em paralelo.
    aguardando: bool = False

    #: Quantas vezes o interlocutor tentou virar as instruções da IA.
    #:
    #: Conta **na sessão**, e não num contador global, porque o que importa é a
    #: insistência dentro da mesma conversa: uma frase esquisita solta é ruído;
    #: duas são intenção, e aí o caso deixa de ser da IA — ver `agent/blindagem.py`.
    tentativas_de_injecao: int = 0

    #: Qual dos três botões de causa o cliente tocou, se tocou algum.
    #:
    #: Guarda o `id`, nunca o rótulo: rótulo é texto que alguém reescreve para
    #: caber em 20 caracteres, `id` é contrato. É por ele que se sabe qual
    #: tratativa o fechamento deste caso deve gerar.
    causa_escolhida: str | None = None

    #: O cliente tocou em «Preciso de ajuda!» e a IA ofereceu a ligação.
    #:
    #: Existe porque a aceitação costuma ser curta. Quem responde «sim» a
    #: «quer que um operador te ligue?» não escreve nada que um detector de
    #: pedido de atendente reconheça, e sem esta marca o escalonamento cairia
    #: no caminho comum, que encerra o caso em vez de mandar para a fila.
    #:
    #: A pergunta é nossa, então a resposta curta é previsível: quem cria o
    #: contexto é quem tem de lembrar dele.
    pediu_ajuda: bool = False

    #: Os `id` de **todas** as mensagens que mandamos nesta conversa.
    #:
    #: ⭐ **É o que liga a resposta ao veículo certo.** Um cliente com frota
    #: aponta todos os caminhões para o mesmo telefone, então mais de uma
    #: ocorrência pode estar viva no mesmo número ao mesmo tempo. Quando a
    #: pessoa toca num botão ou usa o "responder" citando algo nosso, a Meta
    #: devolve `context.id` apontando para a mensagem exata — e é por aqui que
    #: se sabe de qual placa ela está falando.
    #:
    #: ⚠️ **Todas, e não só o template.** A primeira versão disto guardava só a
    #: notificação de abertura, e o buraco apareceu no primeiro teste de frota:
    #: depois do primeiro toque, toda fala da IA ficava inendereçável, e
    #: retomar a conversa do outro caminhão exigia rolar a tela até o template
    #: original. Ninguém faz isso.
    #:
    #: Vazio enquanto nada saiu, e quando o canal não dá id (Twilio). Aí o
    #: roteamento cai na ocorrência viva mais recente, que é palpite.
    nossas_mensagens: set[str] = field(default_factory=set)

    #: Quantas vezes esta conversa ainda pode insistir no silêncio.
    #:
    #: ⚠️ **Só desce, nunca sobe, e o bug que criou este campo mostra por quê.**
    #: A regra "com frota, insiste uma vez só" era calculada na hora, olhando
    #: quantas conversas estavam vivas. Em 01/09/2026 duas conversas rodaram
    #: juntas, uma encerrou primeiro, e a sobrevivente **recuperou o orçamento
    #: de duas insistências** porque naquele instante já era a única viva. O
    #: cliente levou a mesma pergunta duas vezes.
    #:
    #: `None` enquanto ninguém calculou. Depois disso é o mínimo entre o que já
    #: valia e o que vale agora: conversa que nasceu sozinha e ganhou companhia
    #: também é freada.
    teto_de_retomadas: int | None = None

    #: O botão que a pessoa tocou nesta notificação **antes de a vez ser desta
    #: conversa**, guardado para quando ela chegar.
    #:
    #: ⚠️ **A metade que faltava do "uma de cada vez".** Em 01/09/2026 o cliente
    #: tocou nos botões dos dois caminhões, as duas conversas ficaram esperando
    #: resposta ao mesmo tempo, e o "Fui eu" que ele digitou caiu na errada. Ele
    #: escreveu *"eu disse que fui eu da primeira mensagem da outra placa"* e a
    #: IA, sem entender, encerrou.
    #:
    #: Tocar no botão é dizer "vi este alarme", e isso não pode se perder. Mas
    #: também não pode abrir uma segunda frente: a conversa espera a vez, com o
    #: toque guardado aqui, e `_puxar_o_proximo_veiculo` o reaproveita.
    toque_adiado: str | None = None

    #: O toque que **já está desenhado** na conversa do painel, esperando o
    #: registro de verdade.
    #:
    #: ⚠️ **Um toque, dois riscos na tela.** Visto no painel em 01/09/2026: o
    #: cliente aparecia tocando duas vezes em "Está tudo bem!". O toque entra em
    #: `falas` quando a conversa vai para a fila, para ela não ficar só com o
    #: template; quando a vez chega, `registrar_cliente` o registra de novo,
    #: agora com histórico do modelo, e desenha um segundo risco.
    #:
    #: Apagar o primeiro desordenaria a conversa: a resposta da fila entra entre
    #: os dois, e a IA passaria a dizer "anotei o alerta" **antes** de a pessoa
    #: ter tocado. Então o segundo é que não desenha.
    toque_ja_na_tela: str | None = None

    @property
    def pode_retomar(self) -> bool:
        return self.viva and self.retomadas < self.tipo.retomadas_maximas

    @property
    def proxima_espera_s(self) -> int:
        """Quanto esperar desta vez. Decresce a cada retomada — ver `esperas_s`."""
        return self.tipo.espera_da_retomada(self.retomadas)
    handoff: list[str] = field(default_factory=list)
    criada_em: datetime = field(default_factory=lambda: datetime.now(UTC))
    ultima_em: datetime = field(default_factory=lambda: datetime.now(UTC))

    #: O que foi trocado, em ordem, para o painel montar a conversa.
    falas: list[Fala] = field(default_factory=list)
    trilha: list[PassoDaTrilha] = field(default_factory=list)

    @property
    def expirada(self) -> bool:
        return datetime.now(UTC) - self.ultima_em > VALIDADE

    @property
    def viva(self) -> bool:
        return not self.encerrada and not self.expirada

    @property
    def grau(self) -> str:
        """A cor segue a evidência, não só o rótulo do evento.

        Um pânico que a triagem pôs em 15% mostrado em vermelho-crítico ao lado
        de um pânico de 94% ensina o operador a ignorar vermelho. Quando há
        probabilidade e ela é baixa, a linha desce de faixa — e a nota ao lado
        diz o número, para ninguém precisar adivinhar por que a cor mudou.
        """
        faixa = {"CRITICA": "critica", "ALTA": "alta", "MEDIA": "media", "BAIXA": "baixa"}
        base = faixa[self.tipo.criticidade]
        if self.probabilidade_real is None:
            return base
        if self.probabilidade_real >= LIMIAR_ESCALONAMENTO:
            return "critica"
        if self.probabilidade_real >= 40:
            return "alta"
        return "media"

    @property
    def duracao(self) -> str:
        segundos = int((self.ultima_em - self.criada_em).total_seconds())
        return f"{segundos // 60}:{segundos % 60:02d}"

    def anotar(self, ator: str, descricao: str) -> None:
        self.trilha.append(PassoDaTrilha(datetime.now(UTC), ator, descricao))

    def registrar_template(
        self, para_o_modelo: str, para_o_operador: str, botoes: list[str] | None = None
    ) -> None:
        """A notificação pré-aprovada que abriu a conversa.

        **Dois textos porque são duas plateias**, e é essa separação que faz a
        coisa funcionar. O modelo recebe o corpo com um cabeçalho dizendo que
        aquilo já foi entregue e não foi escrito por ele — sem isso ele se
        apresenta e reconta o evento que o cliente acabou de ler. O operador
        recebe o corpo limpo, do jeito que apareceu no celular; cabeçalho de
        instrução na tela dele seria vazamento de andaime.

        **Não conta turno de IA e não soma custo.** O texto foi aprovado pela
        Meta palavra por palavra, e o modelo não participou: gastar um dos
        `MAX_TURNOS_IA` aqui seria tirar da conversa de verdade um turno que
        ela vai precisar.
        """
        self.historico.append(Mensagem(papel="assistant", conteudo=para_o_modelo))
        self.falas.append(
            Fala("ia", para_o_operador, tipo="template", botoes=list(botoes or []))
        )
        self.ultima_em = datetime.now(UTC)

    def registrar_toque_na_fila(self, rotulo: str) -> None:
        """O toque de quem tocou, mas cuja vez ainda não chegou.

        ⚠️ **Só na tela, e é de propósito.** Vai para `falas`, que é o que o
        painel desenha, e **não** para o `historico` do modelo nem para
        `houve_resposta`. Do ponto de vista da conversa, esta ainda não começou:
        o toque vale quando a vez chegar, e aí `_atender_causa` e companhia
        registram direito.

        Existe porque sem ela o painel mostrava a ocorrência com **só o
        template** enquanto o cliente jurava ter tocado no botão. Ele tinha
        tocado; o toque estava na trilha de auditoria, que ninguém abre.
        """
        self.falas.append(Fala("cliente", rotulo))
        self.toque_ja_na_tela = rotulo

    def registrar_frase_com_botoes(self, texto: str, botoes: list[str]) -> None:
        """Uma pergunta que a IA fez com botões, e que já saiu.

        Precisa entrar no histórico do modelo por um motivo específico: sem
        isso ele não sabe que perguntou, e o turno seguinte repete a pergunta
        que a pessoa acabou de responder tocando. É o mesmo defeito do
        `registrar_template`, na versão pequena.

        As opções vão junto do texto para o modelo, porque a resposta que
        chegar vai ser um daqueles rótulos — sem a lista, ele recebe "Em
        manutenção" sem contexto de que aquilo foi uma escolha oferecida.

        **Não conta turno de IA e não soma custo**: a pergunta é do roteiro.

        ⚠️ **E ela avisa que a conversa já tem voz da IA nela.** Sem esse aviso,
        em 28/08/2026, o turno seguinte abriu com «Boa tarde, Bruno!» para
        quem já tinha lido "Que bom, Bruno! Só preciso saber o motivo" e
        tocado um botão. O modelo não estava desobedecendo: pelo que ele via,
        antes dele só existia a notificação automática, que é voz do sistema.

        A notificação **não** carrega esse aviso, e é deliberado: quem responde
        a um alerta automático não estranha ser cumprimentado pela pessoa que
        aparece depois. O que soa mal é o segundo cumprimento, não o primeiro.
        """
        opcoes = " · ".join(botoes)
        self.historico.append(
            Mensagem(
                papel="assistant",
                conteudo=(
                    f"{texto}\n\n[Enviado com botões: {opcoes}. Esta fala é SUA e já "
                    "chegou ao cliente: você já se dirigiu a ele pelo nome nesta "
                    "conversa, então não cumprimente de novo.]"
                ),
            )
        )
        self.falas.append(Fala("ia", texto, tipo="botoes", botoes=list(botoes)))
        self.ultima_em = datetime.now(UTC)

    def registrar_ia(self, texto: str, custo: float, em_audio: bool = False) -> None:
        self.historico.append(Mensagem(papel="assistant", conteudo=texto))
        self.falas.append(Fala("ia", texto, audio=em_audio))
        self.turnos_ia += 1
        self.custo_usd += custo
        self.ultima_em = datetime.now(UTC)

    def registrar_cliente(
        self,
        texto: str,
        transcrito: bool = False,
        duracao_s: float | None = None,
        nota_para_o_modelo: str | None = None,
    ) -> None:
        """A fala da pessoa. `nota_para_o_modelo` **só** para texto que é nosso.

        ⚠️ A nota vai colada ao texto do cliente no histórico do modelo, e é
        exatamente a forma de um ataque de injeção. Por isso ela existe só para
        o caso em que o "texto do cliente" foi escrito por nós: o rótulo de um
        botão que publicamos. Passar nota junto de texto digitado abriria a
        porta que `agent/blindagem.py` existe para fechar.
        """
        # O histórico do modelo recebe só o texto: para a IA, transcrição e
        # digitação são a mesma coisa. Quem precisa saber a diferença é o
        # operador, e essa marca vive na fala, não no prompt.
        conteudo = f"{texto}\n\n{nota_para_o_modelo}" if nota_para_o_modelo else texto
        self.historico.append(Mensagem(papel="user", conteudo=conteudo))

        # ⚠️ **O modelo precisa deste toque; a tela já o tem.** Quando a conversa
        # esteve na fila, o toque foi desenhado na hora em que ela entrou — ver
        # `toque_ja_na_tela`. Desenhar de novo mostraria o cliente tocando duas
        # vezes no mesmo botão, que foi o que apareceu no painel em 01/09/2026.
        if texto == self.toque_ja_na_tela:
            self.toque_ja_na_tela = None
        else:
            self.falas.append(
                Fala(
                    "cliente",
                    texto,
                    audio=transcrito,
                    transcrito=transcrito,
                    duracao_s=duracao_s,
                )
            )
        self.houve_resposta = True
        self.ultima_em = datetime.now(UTC)

    @property
    def pode_encerrar_sem_operador(self) -> bool:
        """As duas condições juntas, e nenhuma delas dispensável.

        A triagem autoriza pela evidência anterior ao contato; a resposta
        confirma que o contato aconteceu. Fechar com só uma das duas é fechar
        por suposição.
        """
        return self.triagem_autoriza_encerrar and self.houve_resposta

    @property
    def fechamento_precisa_de_revisao(self) -> bool:
        """Evento crítico na faixa do meio: a IA atende, mas quem fecha é gente.

        Só vale para evento que passou por triagem. Remoção de bateria e
        velocidade não têm faixa — eles fecham sozinhos e é daí que vem a
        contenção.
        """
        return self.tipo.exige_triagem_previa and not self.triagem_autoriza_encerrar

    #: Até quando os alarmes deste veículo ficam suprimidos.
    #:
    #: `None` com `desativada=True` significa **até a situação mudar** — veículo
    #: em manutenção ou na base do cliente não tem prazo, sai quando voltar a se
    #: mover. Ver `eventos.DESATIVACAO_POR_DESFECHO`.
    desativada_ate: datetime | None = None
    desativada: bool = False

    @property
    def desativacao_expirou(self) -> bool:
        if not self.desativada or self.desativada_ate is None:
            return False
        return datetime.now(UTC) > self.desativada_ate

    def encerrar(
        self,
        motivo: str,
        desfecho: str | None = None,
        horas_de_desativacao: int | None = None,
    ) -> None:
        """Fecha o caso — e, se o desfecho pedir, marca a desativação temporária.

        **Encerrar e desativar não são a mesma coisa** (doc 12). Encerrar diz
        *o caso acabou*; desativar diz *a situação continua, e os próximos
        alarmes dela são esperados*. Os scripts da Central dizem exatamente
        isso: "iremos desconsiderar os eventos enquanto no local".

        Sem essa distinção, o veículo dispara de novo em minutos e alguém
        atende a mesma coisa outra vez — o custo que a IA existe para eliminar.
        """
        self.encerrada = True
        self.motivo_encerramento = motivo
        self.desfecho = desfecho
        self.ultima_em = datetime.now(UTC)

        if desfecho and eventos.desativa_temporariamente(desfecho):
            self.desativada = True
            duracao = eventos.duracao_da_desativacao(desfecho)

            # ⭐ **O prazo que o cliente informou vence o padrão do catálogo.**
            # Regra da Central: sem confirmação de tempo,
            # duas horas; com tempo informado, o tempo dele. Quem sabe quanto
            # dura o transporte é quem está com o veículo.
            #
            # O teto existe porque a conversa não passa das 24 h da Meta:
            # suprimir além disso é prometer o que este atendimento não alcança.
            if horas_de_desativacao and duracao is not None:
                pedida = timedelta(hours=horas_de_desativacao)
                duracao = min(pedida, eventos.DESATIVACAO_MAXIMA_INFORMADA)

            self.desativada_ate = datetime.now(UTC) + duracao if duracao else None


class Sessoes:
    """Depósito das conversas, por telefone.

    ⚠️ **Um telefone pode ter VÁRIAS conversas vivas ao mesmo tempo**, e isso
    mudou em 01/09/2026.

    Este arquivo dizia o contrário: *"um número só pode ter uma conversa por
    vez"*. A premissa veio de imaginar um motorista com um caminhão, e ela cai
    no cliente que mais gera evento: o gestor de frota, cujos veículos estão
    todos cadastrados no mesmo telefone.

    O que acontecia: `abrir()` gravava por telefone e **substituía** a conversa
    anterior. O caminhão B alarmava no meio do atendimento do caminhão A, a
    sessão de A era descartada sem aviso, e a resposta seguinte do gestor caía
    na conversa errada. A ocorrência de A ficava viva no painel, sem desfecho,
    e ninguém percebia — nada falhava.

    Agora cada ocorrência tem a sua sessão, e o telefone indexa uma **lista**.
    Quem decide para qual delas uma resposta vai é a rota, com `por_abertura()`
    quando a Meta manda o `context.id`, e `vivas()` quando não manda.
    """

    def __init__(self) -> None:
        #: Telefone → conversas vivas daquele número, **mais recente primeiro**.
        self._por_telefone: dict[str, list[Sessao]] = {}
        #: Quando cada número falou conosco pela última vez.
        #:
        #: É o que diz se a **janela de 24 h da Meta** está aberta — e isso é
        #: dinheiro: dentro da janela, mensagem é grátis; fora, só template
        #: entrega, e template é cobrado a cada disparo.
        #:
        #: A Central mediu isso na prática (doc 12): *"se eu enviar 10
        #: notificações vai cobrar 10×; se ele responder na primeira, não é
        #: cobrado as outras 9 durante 24 h"*.
        self._ultima_entrada: dict[str, datetime] = {}
        #: Mais recentes primeiro, incluindo as encerradas — é o que o painel lê.
        self._historico: list[Sessao] = []

    def vivas(self, telefone: str) -> list[Sessao]:
        """Todas as conversas vivas deste número, **da mais movimentada para a
        mais parada**.

        ⚠️ **A ordem é por última atividade, não por ordem de criação.** Era por
        criação, e isso fazia "a mais recente" significar a coisa errada: em
        01/09/2026, com dois caminhões abertos, a pessoa passou a conversar
        sobre o primeiro e toda resposta ambígua continuava caindo no segundo,
        que só era "mais novo" porque o evento dele chegou depois.

        O que a pessoa está discutindo agora é o melhor palpite para o que ela
        acabou de escrever. Ordem de chegada do alarme não diz nada sobre isso.

        Faz a poda na leitura, e não por relógio: sessão morta sai da lista na
        primeira vez que alguém pergunta. Sem depósito externo não há como
        varrer, e varrer no `abrir` deixaria passar a que morreu de velha entre
        um evento e outro.
        """
        chave = _chave(telefone)
        vivas = [s for s in self._por_telefone.get(chave, []) if s.viva]
        vivas.sort(key=lambda s: s.ultima_em, reverse=True)
        if vivas:
            self._por_telefone[chave] = vivas
        else:
            self._por_telefone.pop(chave, None)
        return vivas

    def falou_conosco_em(self, telefone: str) -> datetime | None:
        """Quando **a pessoa** falou conosco pela última vez, em qualquer
        conversa deste número.

        Existe para os relógios de silêncio. Eles olham `sessao.ultima_em`, que
        é por conversa, e com frota isso produzia o pior efeito possível: a
        pessoa respondendo sobre um caminhão e **outra conversa cutucando ela no
        meio**, porque aquela ali estava parada há um minuto. Do lado de quem
        recebe é tudo a mesma janela do WhatsApp: quem está conversando não está
        em silêncio.

        ⚠️ **É a entrada dela, não a nossa saída.** A primeira versão disto
        devolvia o `max(ultima_em)` das conversas vivas, e `ultima_em` sobe
        também quando **nós** falamos: um template novo chegando adiava o
        relógio de todas as outras conversas do número, para sempre, enquanto
        eventos continuassem entrando. O relógio existe para medir o silêncio
        **dela**.

        Reaproveita o mesmo registro da janela de 24 h — é a mesma pergunta
        feita para outro fim.
        """
        return self._ultima_entrada.get(_chave(telefone))

    def ativa(self, telefone: str) -> Sessao | None:
        """A conversa viva mais recente deste número.

        ⚠️ **Com frota, "a mais recente" é um palpite**, não uma certeza. Ela é
        o que sobra quando a Meta não diz em qual notificação a pessoa tocou.
        Quem tem o `context.id` deve usar `por_abertura()` antes de cair aqui.
        """
        vivas = self.vivas(telefone)
        return vivas[0] if vivas else None

    def por_nossa_mensagem(self, telefone: str, mensagem_id: str | None) -> Sessao | None:
        """A conversa em que **aquela mensagem nossa** foi dita.

        É o roteamento exato, e o caminho que o fluxo real usa quase sempre:
        tocar num botão faz a Meta devolver `context.id` apontando para a
        mensagem em que a pessoa tocou. Com cinco caminhões em evento no mesmo
        telefone, é isto que diz de qual placa ela está falando.

        Vale para **qualquer** mensagem nossa, não só o template de abertura:
        a fala da IA, a pergunta com botões, a despedida. Quem responde citando
        qualquer uma delas cai na conversa certa.

        `None` quando não veio contexto, quando ele aponta para uma conversa
        que já morreu, ou quando o canal não deu id. Nos três casos quem chama
        decide o que fazer.
        """
        if not mensagem_id:
            return None
        return next(
            (s for s in self.vivas(telefone) if mensagem_id in s.nossas_mensagens),
            None,
        )

    def abrir(
        self,
        telefone: str,
        tipo: TipoEvento,
        canal: str,
        dados: dict[str, str],
        com_operador: bool = True,
        origem: str = "link",
        modelo: str | None = None,
    ) -> Sessao:
        ocorrencia_id = (
            f"OC-{datetime.now(UTC):%Y-%m-%d}-{uuid.uuid4().hex[:4].upper()}-WA"
        )
        sessao = Sessao(
            ocorrencia_id=ocorrencia_id,
            telefone=telefone,
            tipo=tipo,
            canal=canal,
            dados=dados,
            origem=origem,
            # O cérebro é carimbado **aqui**, na abertura, e não lido do `cfg` a
            # cada turno. É o que faz a troca de modelo valer só da próxima
            # conversa em diante, sem trocar o cérebro de ninguém no meio.
            modelo=modelo,
            historico=[
                Mensagem(
                    papel="user",
                    conteudo=atendimento_real.contexto_inicial(tipo, dados, com_operador),
                )
            ],
        )
        # ⚠️ Insere, **nunca substitui**. Até 01/09/2026 esta linha era
        # `self._por_telefone[chave] = sessao`, e o segundo caminhão do mesmo
        # cliente descartava a conversa do primeiro sem deixar rastro.
        chave = _chave(telefone)
        self._por_telefone.setdefault(chave, []).insert(0, sessao)
        self._historico.insert(0, sessao)
        del self._historico[40:]
        return sessao

    def registrar_entrada(self, telefone: str) -> None:
        """Alguém desse número falou conosco agora. Abre a janela de 24 h."""
        self._ultima_entrada[_chave(telefone)] = datetime.now(UTC)

    def janela_aberta(self, telefone: str) -> bool:
        """A janela de 24 h da Meta está aberta para este número?

        ⚠️ **Sem chamador desde 01/09/2026, e é de propósito. Não religue no
        caminho de abertura.**

        Ela decidia se o evento abria por template ou por texto livre, para não
        pagar um template que "sairia grátis de outro jeito". Duas coisas
        derrubaram esse raciocínio:

        * **Template dentro da janela aberta não é cobrado.** A fatura de agosto
          traz 158 templates `UTILITY` enviados dentro da janela, custo R$ 0,00.
          A economia era zero.
        * **E custava a notificação.** O cliente de frota recebia o primeiro
          evento completo e todos os seguintes como frase solta, sem mapa e sem
          botões, porque o primeiro já tinha aberto a janela.

        Fica aqui porque a informação continua verdadeira e útil para medir
        custo: ela diz se o próximo template será cobrado. O que não pode
        voltar é ela escolhendo **como** o evento abre.

        Conservador de propósito: na dúvida devolve `False`.
        """
        ultima = self._ultima_entrada.get(_chave(telefone))
        if ultima is None:
            return False
        return datetime.now(UTC) - ultima < JANELA_DE_ATENDIMENTO

    def por_id(self, ocorrencia_id: str) -> Sessao | None:
        return next((s for s in self._historico if s.ocorrencia_id == ocorrencia_id), None)

    def encerrada_ha_pouco(self, telefone: str, janela: timedelta) -> Sessao | None:
        """A última conversa desse número, se fechou há pouco.

        Existe para o momento em que a pessoa responde **depois** do
        encerramento. Sem isto ela recebia o menu de teste da POC — *"mande
        bateria, ignicao ou panico"* — no meio de um atendimento que acabara de
        ser fechado (observado em 24/08/2026).

        Responder o menu ali é pior que não responder: expõe andaime interno a
        quem não faz ideia do que é, e sugere que a conversa anterior não
        aconteceu.
        """
        chave = _chave(telefone)
        agora = datetime.now(UTC)
        for sessao in self._historico:
            if _chave(sessao.telefone) != chave:
                continue
            return sessao if agora - sessao.ultima_em <= janela else None
        return None

    def todas(self) -> list[Sessao]:
        """Mais recentes primeiro. Alimenta o painel.

        Guarda também as encerradas: uma conversa que sai da tela no instante
        em que termina é uma conversa que ninguém consegue conferir.
        """
        return list(self._historico)

    def limpar(self) -> None:
        self._por_telefone.clear()
        self._historico.clear()
        self._ultima_entrada.clear()


#: Instância única do processo. Vira Redis no Sprint 2.
SESSOES = Sessoes()
