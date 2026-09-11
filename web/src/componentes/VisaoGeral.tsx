import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import { numeroBR } from "../formato";
import type { Barra, EquipamentoReincidente, Metricas, Vital } from "../tipos";
import { GraficoArea } from "./GraficoArea";
import { Chevron, Confere, Info } from "./Icones";

/**
 * Barras horizontais, cortadas no topo N.
 *
 * O corte é explícito na tela ("+3 outros"), nunca silencioso: uma lista
 * truncada sem aviso faz o supervisor somar as barras e concluir que a conta
 * não fecha. A porcentagem continua sendo sobre o total **inteiro**, não sobre
 * o que sobrou — senão os números mudariam só por caber na tela.
 */
function Barras({ dados, limite }: { dados: Barra[]; limite?: number }) {
  const total = dados.reduce((s, d) => s + d.valor, 0);
  const visiveis = limite ? dados.slice(0, limite) : dados;
  const ocultos = dados.length - visiveis.length;
  const somaOculta = dados.slice(visiveis.length).reduce((s, d) => s + d.valor, 0);
  const maximo = Math.max(...visiveis.map((d) => d.valor), 1);

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
 * Cartão de vital. Vira botão só quando existe destino.
 *
 * Um número que parece clicável e não abre nada custa mais caro do que um
 * número parado: o operador tenta uma vez, não acontece nada, e passa a
 * desconfiar do resto da tela.
 */
function CartaoVital({ v, aoAcionar }: { v: Vital; aoAcionar: () => void }) {
  const conteudo = (
    <>
      <div className="label vital-rot">{v.rotulo}</div>
      <div className="vital-num">
        {v.valor}
        {v.unidade && <small>{v.unidade}</small>}
      </div>
      {v.nota && <div className="vital-nota">{v.nota}</div>}
      {v.selo && (
        <div className="vital-selo">
          <Confere />
          {v.selo}
        </div>
      )}
    </>
  );

  const classe = `vital${v.bom ? " vital-bom" : ""}`;
  if (!v.destino) return <div className={classe}>{conteudo}</div>;

  return (
    <button className={`${classe} vital-acionavel`} type="button" onClick={aoAcionar}>
      {conteudo}
      <span className="vital-ir">
        {v.destino === "recall" ? "Ver a lista" : "Ver os casos"}
        <Chevron />
      </span>
    </button>
  );
}

/** Tela 4 — supervisão. Em produção fica restrita ao perfil de supervisor. */
export function VisaoGeral({ aoIrParaEncerrados }: { aoIrParaEncerrados: () => void }) {
  const [m, setM] = useState<Metricas | null>(null);
  const [reincidencia, setReincidencia] = useState<EquipamentoReincidente[]>([]);
  const [erro, setErro] = useState<string | null>(null);
  const recall = useRef<HTMLElement | null>(null);

  /**
   * Rolar até a seção, e não abrir um modal.
   *
   * O modal esconde o resto do painel e exige um passo a mais para fechar. Aqui
   * o supervisor continua na mesma tela, vê a tabela no lugar dela e pode
   * rolar de volta — sem aprender nada novo. O realce é só para não perder o
   * ponto de chegada.
   */
  const irParaRecall = useCallback(() => {
    const alvo = recall.current;
    if (!alvo) return;

    const reduzido = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    alvo.scrollIntoView({ behavior: reduzido ? "auto" : "smooth", block: "start" });
    alvo.focus({ preventScroll: true });

    alvo.classList.remove("destacado");
    // Reinicia a animação quando o mesmo cartão é clicado duas vezes seguidas.
    void alvo.offsetWidth;
    alvo.classList.add("destacado");
  }, []);

  useEffect(() => {
    api
      .metricas()
      .then(setM)
      .catch((e: Error) => setErro(e.message));

    // Falha aqui não derruba a tela: reincidência é análise, não plantão.
    api.reincidencia().then(setReincidencia).catch(() => setReincidencia([]));
  }, []);

  if (erro) return <p className="erro-api">Não foi possível carregar as métricas.<code>{erro}</code></p>;
  if (!m) return <p className="carregando">Carregando…</p>;

  // Esta é a única tela em largura cheia. As outras têm coluna estreita porque
  // o operador lê uma ocorrência por vez; aqui o supervisor compara números, e
  // comparar exige ver junto. Rolar para comparar é o mesmo que não comparar.
  return (
    <main className="quadro painel-cheio">
      <section className="vitais">
        {m.vitais.map((v) => (
          <CartaoVital
            key={v.rotulo}
            v={v}
            aoAcionar={v.destino === "recall" ? irParaRecall : aoIrParaEncerrados}
          />
        ))}
      </section>

      <div className="grade-painel">
        <section className="modulo">
          <div className="modulo-cab">
            <h2>Contenção ao longo do dia</h2>
            <span className="modulo-per">00h–{m.contencao_por_hora.length - 1}h</span>
          </div>
          <GraficoArea
            valores={m.contencao_por_hora}
            ajuda="Contenção = % dos eventos elegíveis que a IA fechou sozinha, sem nenhum operador tocar."
          />
        </section>

        <section className="modulo">
          <div className="modulo-cab">
            <h2>Volume por evento</h2>
            <span className="modulo-per">24 h</span>
          </div>
          <Barras dados={m.volume_por_evento} limite={6} />
        </section>

        <section className="modulo">
          <div className="modulo-cab">
            <h2>Por que a IA escalou</h2>
            <span className="modulo-per">{m.total_escalonamentos} casos</span>
          </div>
          <Barras dados={m.motivos_de_escalonamento} limite={4} />
        </section>

        {reincidencia.length > 0 && <Reincidencia itens={reincidencia} ancora={recall} />}
      </div>

      <p className="nota-papel nota-pe">
        <Info />
        Tela de supervisão — em produção fica restrita ao perfil de supervisor.
      </p>
    </main>
  );
}
