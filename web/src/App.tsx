import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
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
import type { EstadoIA, Fila, Prontidao } from "./tipos";

type Aba = "voce" | "ia" | "encerrados" | "desativados" | "removidos" | "geral";

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

  return {
    tema,
    alterna: () => setTema((t) => (t === "escuro" ? "claro" : "escuro")),
  };
}

export function App() {
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
  const { tema, alterna } = useTema();

  // O botão só aparece se o servidor disser que a tela existe. A rota devolve
  // 404 quando `PAINEL_TESTES_ATIVO` está desligada ou o ambiente é de
  // produção — esconder aqui é conveniência de interface, e a decisão que vale
  // é a do servidor. Uma vez só: a flag não muda enquanto o processo vive.
  useEffect(() => {
    api.catalogoDeTeste().then(() => setTestesLigados(true)).catch(() => setTestesLigados(false));
  }, []);

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

  const frase = degradado
    ? "Sistema degradado"
    : iaAtiva
      ? "IA ativa"
      : "IA desligada";

  return (
    <>
      <header className="topo">
        <div className="quadro largo">
          <div className="marca">
            <Marca />
            <span className="marca-logo">Bahrd</span>
            <span className="marca-risco" aria-hidden="true" />
            <span className="marca-nome">Central IA</span>
          </div>
          <div className="estado">
            <span className={`ponto${degradado ? " ponto-degradado" : ""}`} />
            <span>{frase}</span>
          </div>
          <span
            className="selo-fonte"
            title="Dados de exemplo servidos pela API. Sem conexão com o sistema de rastreamento da Bahrd."
          >
            Amostra
          </span>
          <div className="topo-dir">
            {testesLigados && (
              <button
                className="link-quieto"
                type="button"
                onClick={() => setEnviandoTeste(true)}
              >
                Enviar Eventos de Teste
              </button>
            )}
            <button className="link-quieto" type="button" onClick={alterna}>
              {tema === "escuro" ? "Modo dia" : "Modo noite"}
            </button>
          </div>
        </div>
      </header>

      {enviandoTeste && <EventosDeTeste aoFechar={() => setEnviandoTeste(false)} />}

      <nav className="segmentos" role="tablist" aria-label="Visões">
        <div className="quadro largo">
          <button
            className="seg"
            role="tab"
            aria-selected={aba === "voce"}
            type="button"
            onClick={() => { setAba("voce"); setTela({ nome: "fila" }); }}
          >
            Atendimento humano <b>{fila?.precisa_de_voce.length ?? "–"}</b>
          </button>
          <button
            className="seg"
            role="tab"
            aria-selected={aba === "ia"}
            type="button"
            onClick={() => { setAba("ia"); setTela({ nome: "fila" }); }}
          >
            Atendimento da IA <b>{fila?.ia_esta_fazendo.length ?? "–"}</b>
          </button>
          <button
            className="seg"
            role="tab"
            aria-selected={aba === "encerrados"}
            type="button"
            onClick={() => { setAba("encerrados"); setTela({ nome: "fila" }); }}
          >
            Encerrados <b>{encerrados ?? "–"}</b>
          </button>
          <button
            className="seg"
            role="tab"
            aria-selected={aba === "desativados"}
            type="button"
            onClick={() => { setAba("desativados"); setTela({ nome: "fila" }); }}
          >
            Desativação temporária <b>{desativados ?? "–"}</b>
          </button>
          <button
            className="seg"
            role="tab"
            aria-selected={aba === "removidos"}
            type="button"
            onClick={() => { setAba("removidos"); setTela({ nome: "fila" }); }}
          >
            Números removidos <b>{removidos ?? "–"}</b>
          </button>
          <button
            className="seg"
            role="tab"
            aria-selected={aba === "geral"}
            type="button"
            onClick={() => { setAba("geral"); setTela({ nome: "fila" }); }}
          >
            Visão geral
          </button>
        </div>
      </nav>

      {erro && (
        <p className="erro-api">
          API inacessível em {config.apiBaseUrl}
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
        <VisaoGeral aoIrParaEncerrados={() => setAba("encerrados")} />
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

          <div className="grade-fila">
            {aba === "voce"
              ? fila.precisa_de_voce.map((item, i) => (
                  <LinhaPrecisaDeVoce
                    key={`${item.ocorrencia_id}-${i}`}
                    item={item}
                    aoAbrir={() => setTela({ nome: "ocorrencia", id: item.ocorrencia_id })}
                  />
                ))
              : fila.ia_esta_fazendo.map((item, i) => (
                  <LinhaIaFazendo
                    key={`${item.ocorrencia_id}-${i}`}
                    item={item}
                    aoAbrir={() => setTela({ nome: "vivo", id: item.ocorrencia_id })}
                  />
                ))}
          </div>

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
