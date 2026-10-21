import { useCallback, useEffect, useState } from "react";
import { api, aoPerderASessao, ErroDaApi } from "./api";
import { config } from "./config";
import { LinhaIaFazendo, LinhaPrecisaDeVoce } from "./componentes/Fila";
import { AoVivo } from "./componentes/AoVivo";
import { Desativados } from "./componentes/Desativados";
import { NumerosRemovidos } from "./componentes/NumerosRemovidos";
import { Encerrados } from "./componentes/Encerrados";
import { Marca } from "./componentes/Marca";
import { EventosDeTeste } from "./componentes/EventosDeTeste";
import { Ocorrencia } from "./componentes/Ocorrencia";
import { VisaoGeral } from "./componentes/VisaoGeral";
import { Grafico, Lua, Sair, Sol } from "./componentes/Icones";
import { CampoBusca } from "./componentes/CampoBusca";
import { Login } from "./componentes/Login";
import type { EstadoIA, Fila, Prontidao, SessaoDoPainel } from "./tipos";

export type Aba = "voce" | "ia" | "encerrados" | "desativados" | "removidos" | "geral";

/**
 * A tela ao vivo guarda o **id**, não o item.
 *
 * Guardava o objeto inteiro, capturado no clique — e como a fila é recarregada
 * periodicamente, o item na tela ficava congelado no estado daquele instante.
 * Numa conversa de WhatsApp real isso aparecia como "Abrindo a conversa" para
 * sempre, enquanto a IA já tinha trocado quatro mensagens com a pessoa.
 */
type Tela = { nome: "fila" } | { nome: "ocorrencia"; id: string } | { nome: "vivo"; id: string };

/** Alterna o tema e guarda a escolha. Plantão noturno é o caso real, não enfeite. */
function useTema() {
  const [tema, setTema] = useState<"claro" | "escuro" | null>(
    () => (localStorage.getItem("tema") as "claro" | "escuro" | null) ?? null,
  );

  useEffect(() => {
    const raiz = document.documentElement;
    if (tema === null) raiz.removeAttribute("data-theme");
    else raiz.setAttribute("data-theme", tema === "escuro" ? "dark" : "light");
    if (tema) localStorage.setItem("tema", tema);
  }, [tema]);

  // Sem escolha guardada, vale o do sistema. Sem isto, o primeiro clique no
  // modo noite de um Windows escuro "ligava" o escuro que já estava na tela.
  const efetivo =
    tema ?? (window.matchMedia("(prefers-color-scheme: dark)").matches ? "escuro" : "claro");

  return {
    tema: efetivo,
    alterna: () => setTema(efetivo === "escuro" ? "claro" : "escuro"),
  };
}

/**
 * O painel em si: só existe com sessão. Quem decide se ele aparece é o `App`,
 * lá embaixo, e enquanto o login está na tela nada daqui é montado: nenhuma
 * fila carrega por trás, nenhum atalho de teclado escuta.
 */
function Painel({
  sessao,
  tema,
  alterna,
  aoSair,
}: {
  sessao: SessaoDoPainel;
  tema: "claro" | "escuro";
  alterna: () => void;
  aoSair: () => void;
}) {
  const [fila, setFila] = useState<Fila | null>(null);
  const [encerrados, setEncerrados] = useState<number | null>(null);
  const [desativados, setDesativados] = useState<number | null>(null);
  const [removidos, setRemovidos] = useState<number | null>(null);
  const [estado, setEstado] = useState<EstadoIA | null>(null);
  const [prontidao, setProntidao] = useState<Prontidao | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [aba, setAba] = useState<Aba>("voce");
  const [tela, setTela] = useState<Tela>({ nome: "fila" });
  const [testesLigados, setTestesLigados] = useState(false);
  const [enviandoTeste, setEnviandoTeste] = useState(false);
  // Um campo de busca por aba — trocar de aba não apaga o que a outra tinha
  // digitado.
  const [buscaVoce, setBuscaVoce] = useState("");
  const [buscaIa, setBuscaIa] = useState("");
  const ehAdmin = sessao.perfil === "admin";

  // O botão só aparece se o servidor disser que a tela existe. A rota devolve
  // 404 quando `PAINEL_TESTES_ATIVO` está desligada ou o ambiente é de
  // produção, e 403 para o perfil operador — esconder aqui é conveniência de
  // interface, e a decisão que vale é a do servidor. Uma vez só: a flag não
  // muda enquanto o processo vive.
  //
  // O operador nem pergunta: a resposta seria 403, e é a mesma tela escondida.
  // A troca de modelo mora dentro dessa tela, então some junto.
  useEffect(() => {
    if (!ehAdmin) {
      setTestesLigados(false);
      return;
    }
    api.catalogoDeTeste().then(() => setTestesLigados(true)).catch(() => setTestesLigados(false));
  }, [ehAdmin]);

  const carregar = useCallback(() => {
    Promise.all([api.fila(), api.estado()])
      .then(([f, e]) => {
        setFila(f);
        setEstado(e);
        setErro(null);
      })
      .catch((e: Error) => setErro(e.message));

    // Encerrados fora do `Promise.all`: é um contador, não a fila. Se esta
    // chamada falhar, o número some da aba e o resto do painel continua de pé.
    api.encerrados().then((e) => setEncerrados(e.itens.length)).catch(() => setEncerrados(null));
    // Mesmo tratamento: contador que falha não pode derrubar o painel.
    api.desativados().then((d) => setDesativados(d.length)).catch(() => setDesativados(null));
    api.numerosRemovidos().then((d) => setRemovidos(d.length)).catch(() => setRemovidos(null));

    // Prontidão é consultada à parte: se um banco cair, o painel continua
    // mostrando a fila que já tem em mãos e avisa no cabeçalho.
    api.prontidao().then(setProntidao).catch(() => setProntidao(null));
  }, []);

  // Acompanhando uma conversa ao vivo, 15 s é uma eternidade: a pessoa do
  // outro lado responde em segundos. Fora dessa tela, recarregar devagar é o
  // certo — a fila não muda tanto assim.
  const emTempoReal = tela.nome === "vivo";

  useEffect(() => {
    carregar();
    const id = setInterval(carregar, emTempoReal ? 3000 : 15000);
    return () => clearInterval(id);
  }, [carregar, emTempoReal]);

  // Atalhos de teclado: o operador não deve precisar do mouse durante um plantão.
  //
  // ⚠️ **Duas correções de 03/09/2026, as duas trazidas pelo primeiro
  // formulário do painel.** Antes disso não havia campo nenhum para digitar,
  // então nenhum dos dois problemas podia aparecer:
  //
  // 1. `HTMLSelectElement` faltava no guard. Escolher "Pânico" num `<select>`
  //    digitando a inicial trocaria a aba do painel por baixo do modal.
  // 2. Com o modal aberto, o Escape era tratado nos dois lugares: fechava o
  //    modal e ainda jogava quem estava numa ocorrência de volta para a fila.
  //    Quem fecha agora é só o modal, que é o de cima.
  useEffect(() => {
    const aoTeclar = (ev: KeyboardEvent) => {
      if (
        ev.target instanceof HTMLInputElement ||
        ev.target instanceof HTMLTextAreaElement ||
        ev.target instanceof HTMLSelectElement
      ) {
        return;
      }
      if (enviandoTeste) return;
      if (ev.key === "1") { setAba("voce"); setTela({ nome: "fila" }); }
      if (ev.key === "2") { setAba("ia"); setTela({ nome: "fila" }); }
      if (ev.key === "3") { setAba("encerrados"); setTela({ nome: "fila" }); }
      if (ev.key === "4") { setAba("desativados"); setTela({ nome: "fila" }); }
      if (ev.key === "5") { setAba("removidos"); setTela({ nome: "fila" }); }
      if (ev.key === "6") { setAba("geral"); setTela({ nome: "fila" }); }
      if (ev.key.toLowerCase() === "n") alterna();
      if (ev.key === "Escape") setTela({ nome: "fila" });
    };
    window.addEventListener("keydown", aoTeclar);
    return () => window.removeEventListener("keydown", aoTeclar);
  }, [alterna, enviandoTeste]);

  const degradado = prontidao !== null && prontidao.status !== "pronto";
  const iaAtiva = estado?.ia_ativa ?? true;

  const irPara = (destino: Aba) => {
    setAba(destino);
    setTela({ nome: "fila" });
  };

  const contagens = {
    voce: fila?.precisa_de_voce.length ?? null,
    ia: fila?.ia_esta_fazendo.length ?? null,
    encerrados,
    desativados,
    removidos,
  };

  // A cor é do estado da fila que a aba representa; ver «Cor por aba» no
  // painel.css.
  const abas: { id: Aba; cor: string; rotulo: string; contagem?: number | null }[] = [
    { id: "voce", cor: "humano", rotulo: "Atendimento humano", contagem: contagens.voce },
    { id: "ia", cor: "ia", rotulo: "Atendimento da IA", contagem: contagens.ia },
    { id: "encerrados", cor: "encerrados", rotulo: "Encerrados", contagem: encerrados },
    { id: "desativados", cor: "desativados", rotulo: "Desativação temporária", contagem: desativados },
    { id: "removidos", cor: "removidos", rotulo: "Números removidos", contagem: removidos },
    { id: "geral", cor: "geral", rotulo: "Visão geral" },
  ];

  const frase = degradado
    ? "Sistema degradado"
    : iaAtiva
      ? "IA ativa"
      : "IA desligada";

  // Filtro das duas filas, 100% no cliente, sobre o que `fila` já carregou.
  const buscaAtual = aba === "voce" ? buscaVoce : buscaIa;
  const listaAtual = fila ? (aba === "voce" ? fila.precisa_de_voce : fila.ia_esta_fazendo) : [];
  const alvoFila = buscaAtual.trim().toLowerCase();
  const filaFiltrada = alvoFila
    ? listaAtual.filter((item) =>
        [item.placa, item.interlocutor, item.tipo_evento].some((c) =>
          c.toLowerCase().includes(alvoFila),
        ),
      )
    : listaAtual;

  return (
    <>
      <header className="topo">
        <div className="faixa">
          <div className="marca">
            <Marca />
            <span className="marca-logo">Bahrd</span>
            <span className="marca-risco" aria-hidden="true" />
            <span className="marca-nome">Central IA</span>
          </div>
          <div className="topo-selos">
            <span className={`chip-estado${degradado ? " chip-degradado" : iaAtiva ? "" : " chip-desligada"}`}>
              <span className={`ponto${degradado ? " ponto-degradado" : ""}`} />
              {frase}
            </span>

            {/* O selo segue a FONTE DE DADOS, não o ambiente.
                Estava fixo no código, e isso o fazia mentir nas duas direções:
                continuaria dizendo "Amostra" no dia em que o rastreamento real
                fosse ligado, e sumir dele em produção faria a tela alegar dado
                real onde não há. O que ele afirma é sobre a origem do dado, e
                só a origem pode decidir se ele aparece. */}
            {estado?.fonte_rastreamento === "amostra" && (
              <span
                className="selo-fonte"
                title="Dados de exemplo servidos pela API. Sem conexão com o sistema de rastreamento."
              >
                Amostra
              </span>
            )}

            {/* Este existe para o lado contrário: deixar o ambiente que NÃO é
                produção impossível de confundir. Uma ocorrência de teste tem a
                mesma cara de uma real, e alguém agindo sobre a errada é um
                incidente — não um incômodo. Produção não ganha selo nenhum:
                ausência de aviso é o estado normal. */}
            {estado && estado.ambiente !== "prd-poc" && (
              <span
                className="selo-ambiente"
                title={`Ambiente de ${estado.ambiente}. Nada aqui é atendimento real.`}
              >
                {estado.ambiente.toUpperCase()}
              </span>
            )}
          </div>
          <div className="topo-dir">
            {testesLigados && (
              <button className="botao-topo" type="button" onClick={() => setEnviandoTeste(true)}>
                Enviar eventos de teste
              </button>
            )}
            <button
              className="botao-icone"
              type="button"
              onClick={alterna}
              aria-label={tema === "escuro" ? "Mudar para o modo dia" : "Mudar para o modo noite"}
              title={tema === "escuro" ? "Modo dia" : "Modo noite"}
            >
              {tema === "escuro" ? <Sol /> : <Lua />}
            </button>

            {/* Quem está aqui, e com que perfil. Só com login ligado: sem ele
                (desenvolvimento sem PAINEL_USUARIOS) não há nome para mostrar
                nem sessão de onde sair. */}
            {sessao.login_ativo && sessao.usuario && (
              <>
                <span className="topo-usuario">
                  <span className="usuario-nome" title={`Conectado como ${sessao.usuario}`}>
                    {sessao.usuario}
                  </span>
                  <span className={`selo-perfil selo-perfil-${sessao.perfil}`}>
                    {ehAdmin ? "Admin" : "Operador"}
                  </span>
                </span>
                <button className="botao-topo botao-sair" type="button" onClick={aoSair}>
                  <Sair />
                  Sair
                </button>
              </>
            )}
          </div>
        </div>
      </header>

      {enviandoTeste && ehAdmin && <EventosDeTeste aoFechar={() => setEnviandoTeste(false)} />}

      {/* Cada aba numa linha só, espalhadas pela largura da Visão geral. */}
      <nav className="segmentos" role="tablist" aria-label="Visões">
        <div className="faixa faixa-abas">
          {abas.map((a) => (
            <button
              key={a.id}
              className="seg"
              data-cor={a.cor}
              role="tab"
              aria-selected={aba === a.id}
              type="button"
              onClick={() => irPara(a.id)}
            >
              {a.id === "geral" && <Grafico />}
              {a.rotulo}
              {a.contagem !== undefined && <b>{a.contagem ?? "–"}</b>}
            </button>
          ))}
        </div>
      </nav>

      {erro && (
        <p className="erro-api">
          {/* Vazio significa "mesma origem" — dizer "API inacessível em "
              seguido de nada deixaria a mensagem sem sentido. */}
          API inacessível em {config.apiBaseUrl || "mesma origem"}
          <code>{erro}</code>
        </p>
      )}

      {tela.nome === "ocorrencia" && (
        <Ocorrencia id={tela.id} aoVoltar={() => setTela({ nome: "fila" })} />
      )}

      {tela.nome === "vivo" && (
        <AoVivo
          item={
            [...(fila?.ia_esta_fazendo ?? []), ...(fila?.precisa_de_voce ?? [])].find(
              (i) => i.ocorrencia_id === tela.id,
            ) ?? null
          }
          aoVoltar={() => setTela({ nome: "fila" })}
        />
      )}

      {tela.nome === "fila" && aba === "geral" && (
        <VisaoGeral contagens={contagens} aoIrPara={irPara} />
      )}

      {tela.nome === "fila" && aba === "desativados" && (
        <Desativados aoAbrir={(id) => setTela({ nome: "ocorrencia", id })} />
      )}

      {tela.nome === "fila" && aba === "removidos" && <NumerosRemovidos />}

      {tela.nome === "fila" && aba === "encerrados" && (
        <Encerrados aoAbrir={(id) => setTela({ nome: "ocorrencia", id })} />
      )}

      {tela.nome === "fila" && (aba === "voce" || aba === "ia") && fila && (
        <main className="quadro painel-cheio" role="tabpanel">
          <p className="chamada">
            {aba === "voce"
              ? `${fila.precisa_de_voce.length} ocorrências aguardando um operador, na ordem de prioridade.`
              : `${fila.ia_esta_fazendo.length} ocorrências em atendimento automático agora. Nada aqui precisa de você.`}
          </p>

          <CampoBusca
            valor={buscaAtual}
            aoMudar={aba === "voce" ? setBuscaVoce : setBuscaIa}
            placeholder="Buscar por placa, interlocutor ou evento"
          />

          {filaFiltrada.length === 0 ? (
            <p className="nada">Nenhum resultado para «{buscaAtual}»</p>
          ) : (
            <div className="grade-fila">
              {aba === "voce"
                ? filaFiltrada.map((item, i) => (
                    <LinhaPrecisaDeVoce
                      key={`${item.ocorrencia_id}-${i}`}
                      item={item}
                      aoAbrir={() => setTela({ nome: "ocorrencia", id: item.ocorrencia_id })}
                    />
                  ))
                : filaFiltrada.map((item, i) => (
                    <LinhaIaFazendo
                      key={`${item.ocorrencia_id}-${i}`}
                      item={item}
                      aoAbrir={() => setTela({ nome: "vivo", id: item.ocorrencia_id })}
                    />
                  ))}
            </div>
          )}

          {/* Fora da grade: dentro dela o parágrafo viraria uma célula e
              quebraria o alinhamento dos cartões. */}
          {aba === "voce" && (
            <p className="rodape-lista">
              A IA está cuidando de outras {fila.ia_esta_fazendo.length} ocorrências.{" "}
              <button type="button" onClick={() => setAba("ia")}>
                Ver o atendimento da IA
              </button>
            </p>
          )}
        </main>
      )}

      {tela.nome === "fila" && (aba === "voce" || aba === "ia") && !fila && !erro && (
        <p className="carregando">Carregando a fila…</p>
      )}

      <footer className="pe">
        <div className="quadro largo">
          <span>Painel do operador · POC de IA da Central Bahrd</span>
          <span style={{ marginLeft: "auto" }}>
            <kbd>1</kbd> humano · <kbd>2</kbd> IA · <kbd>3</kbd> encerrados · <kbd>4</kbd> visão
            geral · <kbd>N</kbd> noite · <kbd>Esc</kbd> voltar
          </span>
        </div>
      </footer>
    </>
  );
}

/** Onde a pessoa está: conferindo a sessão, no login, ou dentro do painel. */
type Fase =
  | { nome: "conferindo" }
  | { nome: "login"; aviso?: string }
  | { nome: "painel"; sessao: SessaoDoPainel };

/**
 * A porta do painel.
 *
 * No boot pergunta ao servidor quem está aqui (`GET /painel/sessao`). Com
 * sessão, o painel; sem sessão, só o login. Com o login desligado no servidor
 * (desenvolvimento sem PAINEL_USUARIOS), a resposta é `login_ativo: false` e o
 * painel abre direto, como abria antes do login.
 *
 * ⚠️ **Esconder aqui não é o que protege.** Cada rota do painel confere a
 * sessão no servidor; esta tela só evita mostrar um painel que responderia 401
 * em tudo.
 */
export function App() {
  const { tema, alterna } = useTema();
  const [fase, setFase] = useState<Fase>({ nome: "conferindo" });

  useEffect(() => {
    api
      .sessaoAtual()
      .then((sessao) => setFase({ nome: "painel", sessao }))
      .catch((e: unknown) => {
        // 401 é o normal de quem ainda não entrou: login sem aviso nenhum. O
        // resto (503 de login não configurado, API fora do ar, token da borda
        // errado) vira o aviso da tela, para a pessoa saber que não é a senha.
        const semSessao =
          e instanceof ErroDaApi && e.status === 401 && !e.message.includes("X-Painel-Token");
        setFase({
          nome: "login",
          aviso: semSessao
            ? undefined
            : e instanceof ErroDaApi
              ? e.message
              : `Não foi possível falar com a API em ${config.apiBaseUrl || "mesma origem"}.`,
        });
      });
  }, []);

  // Um 401 de qualquer rota do painel, no meio do uso, traz de volta ao login
  // sem recarregar a página. Só com login ligado: sem ele, um 401 só pode ser o
  // token da borda, e voltar ao login não resolveria nada.
  useEffect(
    () =>
      aoPerderASessao(() =>
        setFase((atual) =>
          atual.nome === "painel" && atual.sessao.login_ativo
            ? { nome: "login", aviso: "Sua sessão terminou. Entre de novo." }
            : atual,
        ),
      ),
    [],
  );

  const sair = () => {
    // Sai da tela mesmo se a API não responder: o cookie tem prazo, e ficar
    // preso num painel que se pediu para fechar é pior.
    api
      .sair()
      .catch(() => undefined)
      .finally(() => setFase({ nome: "login" }));
  };

  if (fase.nome === "conferindo") {
    return <p className="carregando login-conferindo">Conferindo a sessão…</p>;
  }

  if (fase.nome === "login") {
    return (
      <Login
        tema={tema}
        aoAlternarTema={alterna}
        aviso={fase.aviso}
        aoEntrar={(sessao) => setFase({ nome: "painel", sessao })}
      />
    );
  }

  return <Painel sessao={fase.sessao} tema={tema} alterna={alterna} aoSair={sair} />;
}
