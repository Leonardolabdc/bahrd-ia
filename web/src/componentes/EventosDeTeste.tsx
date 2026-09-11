import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type {
  CatalogoDeTeste,
  EstadoDoModelo,
  EventoDisponivel,
  ReciboDeTeste,
} from "../tipos";
import { Chevron } from "./Icones";

/**
 * Onde ficam os números já usados nesta aba do navegador.
 *
 * `sessionStorage` e não `localStorage`: o pedido foi guardar **na sessão**.
 * Fechou a aba, esvazia. Num painel que fica aberto num monitor da Central, uma
 * lista que nunca some viraria cadastro permanente por acidente, com números de
 * gente que passou por ali uma vez.
 */
const CHAVE_USADOS = "eventos-de-teste:numeros-usados";

/**
 * Os recibos dos disparos desta sessão.
 *
 * ⚠️ **Corrige um bug de 03/09/2026.** O recibo era `useState` do modal, e o
 * modal é destruído ao fechar: quem disparava, fechava para olhar a fila e
 * reabria não achava mais o que tinha enviado. Justamente na hora em que o
 * recibo serve para algo, que é comparar o que saiu com o que chegou no celular.
 *
 * `sessionStorage`, como os números: sobrevive a fechar e reabrir o modal e a
 * recarregar a página, e esvazia quando a aba fecha. Um histórico permanente num
 * monitor da Central acumularia telefone de gente que passou por ali uma vez.
 */
const CHAVE_RECIBOS = "eventos-de-teste:recibos";

/** Quantos recibos guardar. O suficiente para uma sessão de teste inteira. */
const MAXIMO_DE_RECIBOS = 10;

/**
 * Quanto tempo o verde de «Mensagem enviada» fica ao lado do botão.
 *
 * ⚠️ **Ele some de propósito.** O registro do que saiu é o histórico abaixo,
 * que fica. Um verde parado enquanto a pessoa já trocou nome e placa
 * confirmaria um envio que não é mais o que está na tela.
 *
 * Tempo suficiente para ler sem tirar os olhos do formulário, e curto o
 * bastante para não sobreviver ao preenchimento do disparo seguinte.
 */
const SEGUNDOS_DA_CONFIRMACAO = 6;

function lerUsados(): string[] {
  try {
    const bruto = sessionStorage.getItem(CHAVE_USADOS);
    return bruto ? (JSON.parse(bruto) as string[]) : [];
  } catch {
    // Aba anônima, armazenamento bloqueado, JSON corrompido. Nada disso pode
    // derrubar a tela: o histórico é conveniência, não funcionalidade.
    return [];
  }
}

function guardarUsado(numero: string): string[] {
  const lista = [numero, ...lerUsados().filter((n) => n !== numero)].slice(0, 8);
  try {
    sessionStorage.setItem(CHAVE_USADOS, JSON.stringify(lista));
  } catch {
    // Idem: se não deu para guardar, a tela continua funcionando.
  }
  return lista;
}

function limparRecibos(): ReciboDeTeste[] {
  try {
    sessionStorage.removeItem(CHAVE_RECIBOS);
  } catch {
    // Nada a fazer: a lista some da tela de qualquer forma.
  }
  return [];
}

function lerRecibos(): ReciboDeTeste[] {
  try {
    const bruto = sessionStorage.getItem(CHAVE_RECIBOS);
    return bruto ? (JSON.parse(bruto) as ReciboDeTeste[]) : [];
  } catch {
    return [];
  }
}

function guardarRecibo(recibo: ReciboDeTeste): ReciboDeTeste[] {
  const lista = [recibo, ...lerRecibos()].slice(0, MAXIMO_DE_RECIBOS);
  try {
    sessionStorage.setItem(CHAVE_RECIBOS, JSON.stringify(lista));
  } catch {
    // Armazenamento cheio ou bloqueado. A lista da tela continua certa nesta
    // aba porque o estado do React já foi atualizado; só não sobrevive a um
    // recarregamento. Perder histórico é melhor que derrubar a tela.
  }
  return lista;
}

/**
 * O número é um celular brasileiro?
 *
 * ⚠️ Espelha `celular_brasileiro` da rota, que é quem manda de verdade. Aqui é
 * só para pintar de vermelho enquanto a pessoa digita; o servidor confere de
 * novo, porque quem chama a rota por fora não passa por esta função.
 *
 * As duas regras que não são só contagem de dígitos: DDD entre 11 e 99, e nove
 * dígitos começando em 9. Sem elas, `+1 415 555 0100` passaria — vira
 * `5514155550100`, que tem o comprimento certo e parece um DDD 14.
 *
 * ⛔ Pega o dígito **faltando**. Não pega o dígito **trocado**: `41999998888` e
 * `41999998889` são os dois válidos, e o segundo é a casa de um estranho. Contra
 * isso não existe validação, só a conferência de quem aperta o botão.
 */
function numeroValido(bruto: string): boolean {
  const digitos = bruto.replace(/\D/g, "");
  const comDdi = digitos.startsWith("55") ? digitos : `55${digitos}`;
  if (comDdi.length < 12 || comDdi.length > 13) return false;

  const ddd = Number(comDdi.slice(2, 4));
  const assinante = comDdi.slice(4);
  if (ddd < 11 || ddd > 99) return false;
  if (assinante.length === 9 && !assinante.startsWith("9")) return false;
  if (assinante.length === 8 && !"6789".includes(assinante[0])) return false;
  return true;
}

/**
 * Destaca os nomes de aba dentro de um texto vindo da API.
 *
 * O servidor manda as abas entre `«»`, e é ele que sabe para onde cada evento
 * vai. Marcar aqui por busca de texto («Encerrados», «Atendimento humano»)
 * quebraria no dia em que uma aba fosse renomeada; a marca vem junto do dado.
 *
 * As aspas somem na renderização: quem lê ganha a cor, que faz o mesmo trabalho
 * sem poluir a frase.
 */
function ComAbasDestacadas({ texto }: { texto: string }) {
  return (
    <>
      {texto.split(/(«[^»]+»)/g).map((parte, i) =>
        parte.startsWith("«") && parte.endsWith("»") ? (
          <b key={i} className="aba-nome">
            {parte.slice(1, -1)}
          </b>
        ) : (
          parte
        ),
      )}
    </>
  );
}

/**
 * A Central dispara evento de teste sozinha, sem Postman e sem chamar o dev.
 *
 * Pedida pelo gestor da Central em 03/09/2026. Até aqui, validar o atendimento
 * exigia montar JSON à mão, saber o formato de data aceito, acertar o rótulo do
 * evento caractere por caractere e perguntar ao Leonardo o que deu errado
 * quando nada acontecia. A tela tira as quatro coisas do caminho: o rótulo vem
 * do catálogo, o horário é sempre agora, o payload é montado no servidor, e a
 * resposta explica a recusa em português.
 *
 * ⛔ **Só o disparo é simulado.** Dali em diante é produção: WhatsApp de
 * verdade, pelo número oficial verificado da Bahrd, para o celular escolhido, e
 * o template e a IA gastando dinheiro real.
 *
 * ⚠️ O risco mais provável não é ataque, é **um dígito errado**. Havia uma lista
 * fechada de destinos por causa disso, e ela saiu em 03/09/2026: a Central
 * precisa testar com o celular de quem estiver na sala. O que restou é a
 * validação de formato, que pega o dígito faltando e não o dígito trocado.
 *
 * Modal e não aba nova, porque foi o pedido e porque está certo: quem testa
 * precisa do painel atrás para ver o caso cair na fila.
 */
export function EventosDeTeste({ aoFechar }: { aoFechar: () => void }) {
  const [catalogo, setCatalogo] = useState<CatalogoDeTeste | null>(null);
  const [tipo, setTipo] = useState("");
  const [telefone, setTelefone] = useState("");
  const [nome, setNome] = useState("");
  const [placa, setPlaca] = useState("ABC1D23");
  const [enviando, setEnviando] = useState(false);
  // Lista, e lida do armazenamento na montagem: é isso que faz o histórico
  // sobreviver a fechar e reabrir o modal.
  const [recibos, setRecibos] = useState<ReciboDeTeste[]>(lerRecibos);
  const [erro, setErro] = useState<string | null>(null);
  const [modelos, setModelos] = useState<EstadoDoModelo | null>(null);
  const [trocando, setTrocando] = useState(false);
  const [usados, setUsados] = useState<string[]>(lerUsados);
  // Só pinta de vermelho depois que a pessoa saiu do campo. Vermelho aparecendo
  // no primeiro dígito acusa quem ainda está digitando.
  const [tocouNoTelefone, setTocouNoTelefone] = useState(false);
  // O aviso colado no «Enviar». Estado próprio, e não `recibos[0]`: os recibos
  // sobrevivem à sessão inteira, e este aqui precisa sumir.
  const [confirmacao, setConfirmacao] = useState<ReciboDeTeste | null>(null);

  // ⚠️ O timer é refeito quando a confirmação troca, e por isso o segundo
  // disparo ganha os segundos inteiros em vez de herdar o resto do primeiro.
  useEffect(() => {
    if (confirmacao === null) return;
    const t = window.setTimeout(
      () => setConfirmacao(null),
      SEGUNDOS_DA_CONFIRMACAO * 1000,
    );
    return () => window.clearTimeout(t);
  }, [confirmacao]);

  // Esc fecha, como no `ModalMapa`. Num plantão a mão está no teclado.
  useEffect(() => {
    const aoTeclar = (ev: KeyboardEvent) => {
      if (ev.key === "Escape") aoFechar();
    };
    window.addEventListener("keydown", aoTeclar);
    return () => window.removeEventListener("keydown", aoTeclar);
  }, [aoFechar]);

  useEffect(() => {
    api
      .catalogoDeTeste()
      .then((c) => {
        setCatalogo(c);
        setTipo((t) => t || c.eventos[0]?.codigo || "");
        // ⛔ **O telefone começa vazio, desde 03/09/2026.**
        //
        // A tela abria com o último número usado nesta sessão, pensando em quem
        // dispara vários eventos seguidos para o mesmo celular. O ganho era um
        // campo já preenchido; o custo era um destino **escolhido pela tela**, e
        // não pela pessoa, num formulário cujo botão manda WhatsApp de verdade.
        //
        // O risco desta tela nunca foi ataque, é o disparo para o número errado.
        // Preencher sozinho transforma "não reparei no campo" em "mandei alarme
        // de pânico para quem usou o painel antes de mim".
        //
        // Os números já usados continuam à mão: são sugestões do `datalist`, que
        // aparecem ao clicar no campo. A diferença é que agora entram por
        // escolha, não por omissão.
      })
      .catch((e: Error) => setErro(e.message));
    api.modelo().then(setModelos).catch(() => setModelos(null));
  }, []);

  const trocarCerebro = useCallback((id: string) => {
    setTrocando(true);
    api
      .trocarModelo(id)
      .then((m) => {
        setModelos(m);
        setCatalogo((c) => (c ? { ...c, modelo_atual: m.atual } : c));
      })
      .catch((e: Error) => setErro(e.message))
      .finally(() => setTrocando(false));
  }, []);

  const escolhido: EventoDisponivel | undefined = catalogo?.eventos.find(
    (e) => e.codigo === tipo,
  );

  const enviar = useCallback(() => {
    setEnviando(true);
    setErro(null);
    // Apaga o verde do disparo anterior antes de começar. Sem isto, o aviso de
    // um envio que já passou ficaria na tela durante o envio seguinte.
    setConfirmacao(null);
    api
      .dispararTeste({
        tipo,
        telefone,
        nome: nome || undefined,
        placa: placa || undefined,
      })
      .then((r) => {
        setRecibos(guardarRecibo(r));
        setConfirmacao(r);
        setCatalogo((c) => (c ? { ...c, usados_hoje: r.usados_hoje } : c));
        // Guarda só o que foi de fato usado. Número digitado e não enviado não
        // vira sugestão: metade dele pode ser um erro de digitação em curso.
        setUsados(guardarUsado(telefone));
      })
      .catch((e: Error) => setErro(e.message))
      .finally(() => setEnviando(false));
  }, [tipo, telefone, nome, placa]);

  const telefoneOk = numeroValido(telefone);
  const noTeto = catalogo !== null && catalogo.usados_hoje >= catalogo.teto_por_dia;

  return (
    <div className="mapa-fundo" role="dialog" aria-modal="true" onClick={aoFechar}>
      <div className="teste-caixa" onClick={(ev) => ev.stopPropagation()}>
        <div className="mapa-cab">
          <div>
            <div className="mapa-titulo">Enviar evento de teste</div>
            <div className="mapa-sub">
              Dispara pelo caminho real e manda WhatsApp de verdade.
            </div>
          </div>
          <button className="mapa-fechar" type="button" onClick={aoFechar} aria-label="Fechar">
            ✕
          </button>
        </div>

        <div className="teste-corpo">
          {catalogo === null && erro === null && <p className="sim-explica">Carregando…</p>}

          {catalogo !== null && (
            <>
              <div className="teste-campos">
                <label className="campo">
                  <span className="campo-nome">Evento</span>
                  <select value={tipo} onChange={(e) => setTipo(e.target.value)}>
                    {catalogo.eventos.map((e) => (
                      <option key={e.codigo} value={e.codigo}>
                        {e.rotulo}
                      </option>
                    ))}
                  </select>
                </label>

                <label className="campo">
                  <span className="campo-nome">
                    Enviar para
                    <span
                      className="campo-dica"
                      title="Celular brasileiro com DDD. Confira o número antes de enviar: um dígito trocado é válido para o sistema e manda o alerta para a casa de um estranho."
                    >
                      ?
                    </span>
                  </span>
                  <input
                    type="tel"
                    inputMode="numeric"
                    value={telefone}
                    placeholder="41999998888"
                    list="numeros-ja-usados"
                    aria-invalid={tocouNoTelefone && !telefoneOk}
                    className={tocouNoTelefone && !telefoneOk ? "campo-invalido" : undefined}
                    onChange={(e) => setTelefone(e.target.value)}
                    onBlur={() => setTocouNoTelefone(true)}
                  />
                  {/* Os números já usados nesta sessão viram sugestão do próprio
                      navegador. `datalist` e não uma lista nossa: continua sendo
                      um campo de digitar, e quem quiser um número novo digita
                      por cima sem precisar fechar nada. */}
                  <datalist id="numeros-ja-usados">
                    {usados.map((n) => (
                      <option key={n} value={n} />
                    ))}
                  </datalist>
                  {tocouNoTelefone && !telefoneOk && (
                    <span className="campo-erro">
                      Celular brasileiro com DDD, como 41999998888.
                    </span>
                  )}
                </label>

                <label className="campo">
                  <span className="campo-nome">Nome do cliente</span>
                  <input
                    type="text"
                    value={nome}
                    placeholder="opcional"
                    onChange={(e) => setNome(e.target.value)}
                  />
                </label>

                <label className="campo">
                  <span className="campo-nome">Placa</span>
                  <input type="text" value={placa} onChange={(e) => setPlaca(e.target.value)} />
                </label>

                {/* ⚠️ Havia um campo de data e hora aqui, tirado em 03/09/2026 a
                    pedido do Leonardo. O horário do evento é sempre o do
                    disparo, decidido no servidor. O campo dava três formas de
                    errar (formato fora do que o parser aceita, fuso trocado,
                    data no passado num evento apresentado como de agora) e
                    resolvia um caso que ninguém tinha. O horário usado volta no
                    recibo, em `disparado_em`. */}
              </div>

              {/* O que vai acontecer, dito ANTES de apertar. Sem isto o disparo
                  devolve um id e ninguém sabe para qual aba olhar. */}
              {escolhido && (
                <div className="teste-previa">
                  <p className="sim-explica">
                    <ComAbasDestacadas texto={escolhido.descricao} />
                  </p>
                </div>
              )}

              {/* ⚠️ Retrátil desde 03/09/2026: os três cartões de modelo eram o
                  maior bloco da tela e empurravam o «Enviar» para fora dela.
                  Trocar de modelo é decisão ocasional; disparar evento é o que
                  se faz o tempo todo.

                  A linha «IA escolhida» solta sumiu junto: o modelo atual passou
                  a ser o próprio rótulo do retrátil, então a informação continua
                  visível sem clique e sem ocupar uma linha só para ela. */}
              {modelos !== null && (
                <details className="teste-modelo">
                  <summary>
                    <Chevron />
                    Modelo de IA
                    {/* A regra em cinco palavras, colada no rótulo: fechado, o
                        bloco precisa dizer sozinho quando vale abrir. Vem do
                        servidor junto da versão longa, para as duas não
                        divergirem quando a política mudar. */}
                    <span className="teste-quando">{modelos.orientacao_curta}</span>
                    <span className="cont">{catalogo.modelo_atual}</span>
                  </summary>
                  <div className="painel-det">
                    <SeletorDeCerebro
                      estado={modelos}
                      trocando={trocando}
                      aoTrocar={trocarCerebro}
                    />
                  </div>
                </details>
              )}

              {/* ⚠️ Reescrito em 03/09/2026, a pedido do Leonardo. A versão
                  anterior interpolava o telefone cru e virava literalmente
                  "para ninguém" com o campo vazio — bug, não só texto confuso.
                  A troca por "o número escolhido acima" evita mostrar um número
                  incompleto enquanto a pessoa ainda digita, e o texto passou a
                  dizer explicitamente O QUE é simulado (o evento, disparado por
                  esta tela em vez de por um veículo real) e O QUE não é (o
                  WhatsApp, o número da Bahrd, o gasto). */}
              {/* ⚠️ Encurtado em 03/09/2026. Dizia a mesma coisa em cinco linhas,
                  e ninguém lê cinco linhas de aviso duas vezes. O que precisa
                  ficar de pé é a fronteira: o disparo é de mentira, o resto não. */}
              <div className="teste-aviso">
                ⚠️ <b>Só o disparo é simulado.</b> O WhatsApp sai de verdade, pelo número
                oficial da Bahrd, e gasta dinheiro real.
              </div>

              {noTeto && (
                <p className="simulador-erro">
                  Teto de {catalogo.teto_por_dia} testes por dia atingido. Zera à meia-noite.
                </p>
              )}
            </>
          )}

          {erro !== null && <p className="simulador-erro">{erro}</p>}

          {/* ⛔ **O rodapé é o último elemento e é `sticky`.**
              Antes ficava no meio, e com o seletor de modelo aberto e três
              recibos no histórico o «Enviar» saía da tela: quem ia disparar
              tinha de rolar para achar o botão principal da tela.

              Grudado no fim do modal, ele aparece em qualquer altura do rolamento
              e sem depender de quanto conteúdo há acima. O orçamento do dia vem
              junto porque é a informação que decide se ainda dá para apertar. */}
          {/* Mais recente em cima. Quem acabou de disparar olha o topo; quem
              está comparando dois envios rola para baixo. */}
          {recibos.length > 0 && (
            <details className="teste-historico" open={recibos.length === 1}>
              {/* Aberto no primeiro envio e fechado a partir do segundo: quem
                  acabou de disparar quer ver o recibo sem clicar, e quem já fez
                  vários quer o formulário de volta na altura da tela. */}
              <summary>
                <Chevron />
                Enviados nesta sessão
                <span className="cont">{recibos.length}</span>
              </summary>
              <div className="painel-det">
                <button
                  className="link-quieto teste-limpar"
                  type="button"
                  onClick={() => setRecibos(limparRecibos())}
                >
                  Limpar
                </button>
                {recibos.map((r) => (
                  <Recibo key={`${r.evento_id ?? r.disparado_em}-${r.para}`} recibo={r} />
                ))}
              </div>
            </details>
          )}

          {catalogo !== null && (
            <div className="teste-pe">
              <span className="teste-orcamento">
                {catalogo.usados_hoje} de {catalogo.teto_por_dia} testes hoje
              </span>
              {/* Aviso e botão no mesmo bloco, encostados na direita: o pedido
                  foi o indicador ao LADO do «Enviar», e é ali que o olho está
                  no instante em que a confirmação importa. */}
              <div className="teste-pe-acao">
                {confirmacao !== null && (
                  <span
                    className={
                      confirmacao.aceito
                        ? "teste-confirmacao"
                        : "teste-confirmacao teste-confirmacao-falhou"
                    }
                    role="status"
                  >
                    {/* A bolinha acompanha o texto porque cor sozinha não é
                        aviso para quem não a distingue. */}
                    <span className="teste-bolinha" aria-hidden="true" />
                    {confirmacao.aceito ? "Mensagem enviada" : "Não foi enviada"}
                  </span>
                )}
                <button
                  className="btn btn-primario"
                  type="button"
                  onClick={enviar}
                  disabled={enviando || !telefoneOk || noTeto || !tipo}
                >
                  {enviando ? "Enviando…" : "Enviar evento"}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/**
 * Qual cérebro atende o WhatsApp do cliente.
 *
 * ⚠️ **Não é um seletor de teste.** Alguém da Central que vê a IA respondendo
 * mal troca o modelo aqui, e a troca vale para o atendimento de cliente de
 * verdade, **da próxima conversa em diante**. Quem já está falando com a IA
 * termina no cérebro em que começou.
 *
 * ⛔ **O texto ao lado precisa dizer o defeito, não só o preço.** O doc 06
 * conclui que trocar de modelo é o item de menor retorno da lista. Se a tela
 * mostrar só "26x mais barato", alguém deixa o Flash Lite ligado e a Central
 * otimiza a coisa errada, num sistema em que o erro caro é tratar roubo como
 * rotina.
 */
function SeletorDeCerebro({
  estado,
  trocando,
  aoTrocar,
}: {
  estado: EstadoDoModelo;
  trocando: boolean;
  aoTrocar: (id: string) => void;
}) {
  return (
    <div className="teste-cerebro">
      <div className="campo-nome">
        Modelo de IA
        <span
          className="campo-dica"
          title="Vale da próxima conversa em diante. Quem já está falando com a IA neste momento termina no modelo em que começou."
        >
          ?
        </span>
      </div>
      {/* A orientação vem do servidor, junto da lista: é política de operação e
          muda quando a medição mudar. Escrita aqui, viraria um parágrafo que
          ninguém revisa no dia em que o modelo for reavaliado. */}
      <p className="cerebro-orientacao">{estado.orientacao}</p>
      {estado.disponiveis.map((m) => {
        const atual = m.id === estado.atual;
        return (
          <button
            key={m.id}
            className={`cerebro-opcao${atual ? " cerebro-atual" : ""}`}
            type="button"
            disabled={trocando || atual}
            onClick={() => aoTrocar(m.id)}
          >
            {/* ⚠️ Havia um selo "não aprovado para produção" aqui, e um texto
                com os dois defeitos medidos do Flash Lite. Os dois saíram a
                pedido do Leonardo em 03/09/2026. O que restou avisando é a
                orientação no topo do bloco; o fato continua no campo
                `aprovado_para_producao` que a API devolve, para quem for
                consultar a decisão por fora do painel. */}
            <span className="cerebro-topo">
              <b>{m.nome}</b>
              {atual && <span className="cerebro-em-uso">em uso</span>}
            </span>
            {/* Custo e comparação lado a lado. Só o número não diz nada a quem
                não tem o outro na cabeça para comparar.

                ⚠️ O valor já inclui o template da Meta, e a conta aberta fica
                logo abaixo. Sem isso a tela mostraria 26x de diferença, que é a
                razão entre as partes de IA; com o template, que custa o mesmo
                nos dois, a diferença real cai para cerca de 3x. */}
            <span className="cerebro-custo">
              {m.custo}
              {m.custo_comparativo && (
                <span className="cerebro-comparativo">{m.custo_comparativo}</span>
              )}
            </span>
            <span className="cerebro-conta">{m.custo_detalhe}</span>
            {/* Vazio não vira linha em branco. Os dois têm resumo hoje, mas a
                linha já ficou vazia uma vez e o espaço fantasma desalinhava os
                cartões — a guarda custa nada e evita a volta do sintoma. */}
            {m.resumo && <span className="cerebro-resumo">{m.resumo}</span>}
          </button>
        );
      })}
      <p className="sim-onde">
        A troca vale da <b>próxima conversa</b>. As que já estão acontecendo terminam no
        modelo de IA em que começaram.
      </p>
    </div>
  );
}

/**
 * O recibo fica, não pisca.
 *
 * Quem disparou vai olhar o celular e voltar. Um aviso passageiro obrigaria a
 * pessoa a lembrar o que leu, e o que ela precisa lembrar é justamente o que
 * deu errado quando nada chegou.
 *
 * ⚠️ E fica **entre aberturas do modal**, desde 03/09/2026. Era estado local, e
 * o modal é destruído ao fechar: quem disparava, ia olhar a fila e voltava não
 * achava mais o que tinha enviado. Agora a lista mora no `sessionStorage`.
 */
function Recibo({ recibo }: { recibo: ReciboDeTeste }) {
  return (
    <div className={`teste-recibo${recibo.aceito ? "" : " teste-recibo-recusado"}`}>
      <div className="teste-recibo-topo">
        <b>{recibo.aceito ? "Enviado" : "Não enviado"}</b>
        <span className="teste-recibo-hora">{recibo.disparado_em}</span>
      </div>
      <p className="sim-explica">{recibo.resumo}</p>
      {/* Nome e placa antes do telefone: numa bateria de testes o número é
          sempre o mesmo, e é o par nome/placa que distingue um envio do outro.
          Vazio não vira espaço em branco. */}
      <div className="simulador-saida">
        <span>{recibo.rotulo}</span>
        {recibo.nome && <span>{recibo.nome}</span>}
        {recibo.placa && <span>{recibo.placa}</span>}
        <span>{recibo.para}</span>
        {recibo.ocorrencia_id && <span>{recibo.ocorrencia_id}</span>}
      </div>
      <details className="teste-json">
        <summary>Ver o JSON que foi montado</summary>
        <pre>{JSON.stringify(recibo.payload, null, 2)}</pre>
      </details>
    </div>
  );
}
