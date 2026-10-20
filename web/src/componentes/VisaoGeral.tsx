import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import { numeroBR } from "../formato";
import type { Aba } from "../App";
import type { Barra, EquipamentoReincidente, Metricas } from "../tipos";
import { GraficoArea } from "./GraficoArea";
import { Info } from "./Icones";

/**
 * Barras horizontais, cortadas no topo N.
 *
 * O corte é explícito na tela ("+3 outros"), nunca silencioso: uma lista
 * truncada sem aviso faz o supervisor somar as barras e concluir que a conta
 * não fecha. A porcentagem continua sendo sobre o total **inteiro**, não sobre
 * o que sobrou — senão os números mudariam só por caber na tela.
 */
function Barras({ dados, limite, vazio }: { dados: Barra[]; limite?: number; vazio?: string }) {
  const total = dados.reduce((s, d) => s + d.valor, 0);
  const visiveis = limite ? dados.slice(0, limite) : dados;
  const ocultos = dados.length - visiveis.length;
  const somaOculta = dados.slice(visiveis.length).reduce((s, d) => s + d.valor, 0);
  const maximo = Math.max(...visiveis.map((d) => d.valor), 1);

  if (!dados.length) {
    return <p className="modulo-vazio">{vazio ?? "Sem dados ainda."}</p>;
  }

  return (
    <div className="barras">
      {visiveis.map((d) => (
        <div className="barra-linha" key={d.rotulo} title={`${d.rotulo}: ${numeroBR(d.valor)}`}>
          <div className="barra-rot">{d.rotulo}</div>
          <div className="barra-val">
            {numeroBR(d.valor)} <i>{Math.round((d.valor / total) * 100)}%</i>
          </div>
          <div className="barra-trilho">
            <div className="barra-fill" style={{ width: `${(d.valor / maximo) * 100}%` }} />
          </div>
        </div>
      ))}
      {ocultos > 0 && (
        <div className="barra-resto">
          + {ocultos} {ocultos === 1 ? "outro" : "outros"} · {numeroBR(somaOculta)} no total
        </div>
      )}
    </div>
  );
}

/** Moldura vazia do gráfico de linha, quando ainda não há nenhum caso hoje. */
function GraficoVazio({ nota }: { nota: string }) {
  return (
    <div className="grafico-vazio">
      <p className="modulo-vazio">{nota}</p>
    </div>
  );
}

/**
 * Rastreadores que disparam o mesmo alerta e nunca têm causa real.
 *
 * O título evita "reincidência" de propósito: quem lê esta tela é supervisor de
 * central e gestor de frota, não engenheiro. "Dispara sem motivo" descreve o
 * fato observado; "reincidente" obriga a decorar uma definição.
 *
 * A contagem é aritmética sobre o desfecho que o **operador** registrou —
 * nenhum modelo participa. É deliberado: apontar um rastreador para inspeção
 * com base em inferência de IA trocaria um problema de manutenção por uma
 * aposta. Aqui cada número é conferível linha a linha.
 *
 * O que importa não é o volume sozinho — caminhão que roda muito dispara
 * muito. O que denuncia defeito é o alerta repetir e **nunca** ter causa real.
 */
//: Quantos rastreadores cabem sem empurrar a tela para baixo.
const LINHAS_RECALL = 5;

function Reincidencia({
  itens,
  ancora,
}: {
  itens: EquipamentoReincidente[];
  ancora: React.RefObject<HTMLElement | null>;
}) {
  const candidatos = itens.filter((i) => i.candidato_a_recall);
  const ordenados = [...itens].sort(
    (a, b) => Number(b.candidato_a_recall) - Number(a.candidato_a_recall)
      || b.confirmados_sem_causa - a.confirmados_sem_causa,
  );
  const visiveis = ordenados.slice(0, LINHAS_RECALL);
  const ocultos = ordenados.length - visiveis.length;

  // Cliente e IMEI saíram das colunas para caber sem rolagem. Continuam
  // disponíveis no `title` da linha — informação de conferência, não de
  // varredura: ninguém decide inspecionar um rastreador pelo nome do cliente.
  return (
    <section className="modulo" id="recall" ref={ancora} tabIndex={-1}>
      <div className="modulo-cab">
        <h2>Rastreadores que disparam sem motivo</h2>
        <span className="modulo-per">90 d</span>
      </div>

      <table className="tabela tabela-recall">
        <thead>
          <tr>
            {/* A coluna sempre mostrou `i.placa`. O rótulo dizia "Veículo",
                que numa frota significa o caminhão inteiro e não o
                identificador dele. Alinhado com a ficha em 03/09/2026. */}
            <th>Placa</th>
            <th>Evento</th>
            <th className="num">90 d</th>
            <th className="num">Sem causa</th>
            <th>Último</th>
          </tr>
        </thead>
        <tbody>
          {visiveis.map((i) => (
            <tr
              key={`${i.imei}-${i.tipo_evento}`}
              className={i.candidato_a_recall ? "recall" : ""}
              title={`${i.cliente ?? "—"} · IMEI ${i.imei} · ${i.motivo}`}
            >
              <td>
                <b>{i.placa}</b>
                {i.candidato_a_recall && <span className="selo-recall">inspecionar</span>}
              </td>
              <td>{i.tipo_evento}</td>
              <td className="num">{i.ocorrencias_90d}</td>
              <td className="num">{i.confirmados_sem_causa}</td>
              <td>{i.ultimo_em}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <p className="modulo-rodape">
        <b>{candidatos.length}</b> de {itens.length} atendem ao critério — 3+ alertas do mesmo
        tipo, 2+ sem causa real{ocultos > 0 && `. +${ocultos} fora da lista`}
      </p>
    </section>
  );
}

/**
 * Um quadro da Visão geral: título, um complemento à direita e o conteúdo.
 *
 * ⭐ A Visão geral no desenho em quadros brancos sobre o fundo, em vez de uma
 * folha corrida.
 */
function Quadro({
  titulo,
  extra,
  className,
  children,
}: {
  titulo: string;
  extra?: React.ReactNode;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <section className={`quadro-vg${className ? ` ${className}` : ""}`}>
      <div className="quadro-vg-cab">
        <h2>{titulo}</h2>
        {extra && <span className="quadro-vg-extra">{extra}</span>}
      </div>
      {children}
    </section>
  );
}

/** As contagens que o App já tem para as abas de casos (todas, menos "Visão geral"). */
export type Contagens = Record<"voce" | "ia" | "encerrados" | "desativados" | "removidos", number | null>;

/**
 * As contagens das abas, cada uma levando para a sua aba.
 *
 * Só «Atendimento humano» ganha cor, e só com alguém esperando: é o único
 * número desta fileira que pede ação agora. Os outros coloridos não
 * hierarquizam nada.
 */
const CONTADORES: { id: keyof Contagens; rotulo: string }[] = [
  { id: "voce", rotulo: "Atendimento humano" },
  { id: "ia", rotulo: "Atendimento da IA" },
  { id: "encerrados", rotulo: "Encerrados" },
  { id: "desativados", rotulo: "Desativação temporária" },
  { id: "removidos", rotulo: "Números removidos" },
];

function Contadores({ contagens, aoIrPara }: { contagens: Contagens; aoIrPara: (a: Aba) => void }) {
  return (
    <div className="contadores">
      {CONTADORES.map((c) => {
        const n = contagens[c.id];
        const urgente = c.id === "voce" && (n ?? 0) > 0;
        return (
          <button
            key={c.id}
            type="button"
            className={`contador${urgente ? " contador-urgente" : ""}`}
            onClick={() => aoIrPara(c.id)}
            title={`Abrir «${c.rotulo}»`}
          >
            <span className="contador-num">{n ?? "–"}</span>
            <span className="contador-rot">{c.rotulo}</span>
          </button>
        );
      })}
    </div>
  );
}

/**
 * Um anel de 0 a 100%: um número só, com o trilho mostrando quanto falta.
 *
 * Sem dado, o trilho fica vazio e o centro diz «—»: zero seria afirmar um
 * resultado que ainda não existe.
 */
function Anel({ fracao, rotulo, bom }: { fracao: number | null; rotulo: string; bom?: boolean }) {
  const raio = 40;
  const volta = 2 * Math.PI * raio;
  const pct = fracao === null ? null : Math.round(fracao * 100);
  return (
    <figure className="anel" title={pct === null ? `${rotulo}: sem casos ainda` : `${rotulo}: ${pct}%`}>
      <svg viewBox="0 0 100 100" aria-hidden="true">
        <circle className="anel-trilho" cx="50" cy="50" r={raio} />
        {fracao !== null && fracao > 0 && (
          <circle
            className={`anel-valor${bom ? " anel-bom" : ""}`}
            cx="50"
            cy="50"
            r={raio}
            strokeDasharray={`${volta * fracao} ${volta}`}
            transform="rotate(-90 50 50)"
          />
        )}
      </svg>
      <span className="anel-centro">{pct === null ? "—" : `${pct}%`}</span>
      <figcaption>{rotulo}</figcaption>
    </figure>
  );
}

/** Uma linha «rótulo · n/total» com a barra embaixo, como no painel de referência. */
function Progresso({ rotulo, valor, total }: { rotulo: string; valor: number; total: number }) {
  return (
    <div className="progresso" title={`${rotulo}: ${valor} de ${total}`}>
      <div className="progresso-cab">
        <span>{rotulo}</span>
        <b>
          {numeroBR(valor)}/{numeroBR(total)}
        </b>
      </div>
      <div className="progresso-trilho">
        {total > 0 && valor > 0 && (
          <div className="progresso-fill" style={{ width: `${(valor / total) * 100}%` }} />
        )}
      </div>
    </div>
  );
}

function fracao(parte: number, total: number): number | null {
  return total > 0 ? parte / total : null;
}

/** Tela 4 — supervisão. Em produção fica restrita ao perfil de supervisor. */
export function VisaoGeral({
  contagens,
  aoIrPara,
}: {
  contagens: Contagens;
  aoIrPara: (a: Aba) => void;
}) {
  const [m, setM] = useState<Metricas | null>(null);
  const [reincidencia, setReincidencia] = useState<EquipamentoReincidente[]>([]);
  const [erro, setErro] = useState<string | null>(null);
  const recall = useRef<HTMLElement | null>(null);

  const carregar = useCallback(() => {
    api
      .metricas()
      .then((r) => {
        setM(r);
        setErro(null);
      })
      .catch((e: Error) => setErro(e.message));

    // Falha aqui não derruba a tela: reincidência é análise, não plantão.
    api.reincidencia().then(setReincidencia).catch(() => setReincidencia([]));
  }, []);

  useEffect(() => {
    carregar();
    // As contagens de cima já se atualizam com o App; os números da sessão,
    // no mesmo passo, para as duas metades da tela não discordarem.
    const id = setInterval(carregar, 15000);
    return () => clearInterval(id);
  }, [carregar]);

  if (erro) return <p className="erro-api">Não foi possível carregar as métricas.<code>{erro}</code></p>;
  if (!m) return <p className="carregando">Carregando…</p>;

  const r = m.resumo ?? { atendidos: 0, pela_ia: 0, pelo_operador: 0, escalados: 0, custo_medio_usd: 0 };
  const encerradas = r.pela_ia + r.pelo_operador;

  // ⚠️ **Dois vitais sem lugar no novo desenho, mantidos de propósito.**
  // O layout de referência (painel de outro projeto, mais rico) não previa
  // "1º contato" nem "Falsos fechamentos" — este painel tem os dois, e o
  // prompt pediu para não apagar dado que já existia. Entram como uma linha
  // pequena de texto, abaixo da grade principal do "Resumo de atendimentos":
  // é o canto mais discreto do novo layout que ainda assim fica visível sem
  // disputar atenção com os números grandes.
  const primeiroContato = m.vitais.find((v) => v.rotulo === "1º contato");
  const falsosFechamentos = m.vitais.find((v) => v.rotulo === "Falsos fechamentos");

  // Esta é a única tela em largura cheia. As outras têm coluna estreita porque
  // o operador lê uma ocorrência por vez; aqui o supervisor compara números, e
  // comparar exige ver junto. Rolar para comparar é o mesmo que não comparar.
  return (
    <main className="quadro painel-cheio visao-geral">
      <Quadro
        titulo="Atendimentos no painel"
        extra={
          <button type="button" className="botao-atualizar" onClick={carregar} title="Atualizar agora">
            Atualizar
          </button>
        }
      >
        <Contadores contagens={contagens} aoIrPara={aoIrPara} />
      </Quadro>

      <div className="grade-vg">
        <Quadro titulo="Resumo de atendimentos" extra="nesta sessão">
          <div className="resumo-numeros">
            <div>
              <span className="resumo-num">{numeroBR(r.atendidos)}</span>
              <span className="resumo-rot">Atendidos</span>
            </div>
            <button type="button" onClick={() => aoIrPara("encerrados")} title="Ver os encerrados">
              <span className="resumo-num resumo-bom">{numeroBR(r.pela_ia)}</span>
              <span className="resumo-rot">Fechados pela IA</span>
            </button>
            <button type="button" onClick={() => aoIrPara("encerrados")} title="Ver os encerrados">
              <span className="resumo-num">{numeroBR(r.pelo_operador)}</span>
              <span className="resumo-rot">Fechados pelo operador</span>
            </button>
            <div>
              <span className="resumo-num">
                <small>US$</small> {r.custo_medio_usd.toFixed(3).replace(".", ",")}
              </span>
              <span className="resumo-rot">Custo por atendimento</span>
            </div>
          </div>

          {(primeiroContato || falsosFechamentos) && (
            <div className="resumo-extra">
              {primeiroContato && (
                <span>
                  <b>
                    {primeiroContato.valor}
                    {primeiroContato.unidade}
                  </b>{" "}
                  {primeiroContato.rotulo.toLowerCase()}
                  {primeiroContato.nota && ` · ${primeiroContato.nota}`}
                </span>
              )}
              {falsosFechamentos && (
                <span>
                  <b>{falsosFechamentos.valor}</b> {falsosFechamentos.rotulo.toLowerCase()}
                  {falsosFechamentos.selo && ` · ${falsosFechamentos.selo}`}
                </span>
              )}
            </div>
          )}

          {/* Enquanto as ocorrências vivem em memória, estes números são da
              sessão atual da API e zeram no próximo deploy. Dizer isso na tela
              é o que separa "contenção de 50%" de "50% dos dois casos que
              rodaram hoje". */}
          <p className="aviso-sessao">
            Números desta sessão da API. Zeram quando a aplicação reinicia — a persistência em
            banco ainda não está ligada.
          </p>
        </Quadro>

        <Quadro titulo="Desempenho da IA" extra="nesta sessão">
          <div className="desempenho">
            <div className="aneis">
              <Anel fracao={fracao(r.pela_ia, r.atendidos)} rotulo="Contenção" bom />
              <Anel fracao={fracao(r.escalados, r.atendidos)} rotulo="Escalados" />
            </div>
            <div className="progressos">
              <Progresso rotulo="Fechados pela IA, sem operador" valor={r.pela_ia} total={r.atendidos} />
              <Progresso rotulo="Passados para uma pessoa" valor={r.escalados} total={r.atendidos} />
              <Progresso rotulo="Encerrados pelo operador" valor={r.pelo_operador} total={encerradas} />
            </div>
          </div>
          <p className="aviso-sessao">
            Contenção = % dos atendidos que a IA fechou sozinha, sem nenhum operador tocar.
          </p>
        </Quadro>
      </div>

      <div className="grade-vg grade-vg-3">
        <Quadro titulo="Volume por evento" extra="nesta sessão">
          <Barras
            dados={m.volume_por_evento}
            limite={6}
            vazio="Cada evento disparado aparece aqui, agrupado por tipo."
          />
        </Quadro>

        <Quadro
          titulo="Por que a IA escalou"
          extra={m.total_escalonamentos === 1 ? "1 caso" : `${m.total_escalonamentos} casos`}
        >
          <Barras
            dados={m.motivos_de_escalonamento}
            limite={4}
            vazio="Quando a IA passar um caso para uma pessoa, o motivo entra aqui."
          />
        </Quadro>

        <Quadro
          titulo="Contenção ao longo do dia"
          extra={
            m.contencao_por_hora.length
              ? `${String(m.contencao_por_hora.findIndex((v) => v !== null)).padStart(2, "0")}h–${String(m.contencao_por_hora.length - 1).padStart(2, "0")}h`
              : "hoje, nesta sessão"
          }
        >
          {m.contencao_por_hora.length ? (
            <GraficoArea
              valores={m.contencao_por_hora}
              ajuda="Contenção por hora = % dos atendidos naquela hora que a IA fechou sozinha, sem nenhum operador tocar. Hora sem caso fica vazia."
            />
          ) : (
            <GraficoVazio nota="A curva aparece com o primeiro caso de hoje. Hora sem caso fica vazia, não conta como 0%." />
          )}
        </Quadro>
      </div>

      {reincidencia.length > 0 && (
        <div className="quadro-vg">
          <Reincidencia itens={reincidencia} ancora={recall} />
        </div>
      )}

      <p className="nota-papel nota-pe">
        <Info />
        Tela de supervisão — em produção fica restrita ao perfil de supervisor.
      </p>
    </main>
  );
}
