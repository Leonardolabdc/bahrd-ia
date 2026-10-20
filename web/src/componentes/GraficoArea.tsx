import { useEffect, useRef, useState } from "react";

/**
 * Contenção ao longo do dia.
 *
 * ⭐ **Com dado de verdade**, calculado em `_contencao_por_hora` (back-end).
 * Duas regras por causa disso:
 *  · escala inteira, 0–100%: o dado real vai de 0 a 100, e cortar o eixo sem
 *    avisar seria engano visual;
 *  · **hora sem caso é `null` e fica vazia** — a linha se interrompe ali, em vez
 *    de descer a um "0%" que não aconteceu. Ponto isolado vira só o ponto.
 *
 * Mantidas do protótipo: rótulo direto só no último ponto, e marcas de 5 em 5
 * horas no eixo x.
 */
const MIN = 0;
const MAX = 100;
const ALTURA = 230;
const PAD_TOPO = 14;
const PAD_BASE = 10;
//: Faixa à esquerda para os rótulos 25/50/75%, fora da área pintada.
const PAD_ESQ = 34;

type Ponto = { x: number; y: number; v: number; i: number };

/** Trechos de horas seguidas com caso: cada um vira uma linha (e uma área). */
function trechos(pontos: (Ponto | null)[]): Ponto[][] {
  const lista: Ponto[][] = [];
  let atual: Ponto[] = [];
  for (const p of pontos) {
    if (p) atual.push(p);
    else if (atual.length) {
      lista.push(atual);
      atual = [];
    }
  }
  if (atual.length) lista.push(atual);
  return lista;
}

export function GraficoArea({
  valores: todasAsHoras,
  ajuda,
}: {
  valores: (number | null)[];
  /** O que a métrica significa. Aparece ao pousar o mouse sobre o gráfico. */
  ajuda?: string;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const [largura, setLargura] = useState(0);
  const [foco, setFoco] = useState<number | null>(null);

  useEffect(() => {
    const alvo = wrap.current;
    if (!alvo) return;
    const observador = new ResizeObserver(([e]) => setLargura(e.contentRect.width));
    observador.observe(alvo);
    return () => observador.disconnect();
  }, []);

  // ⭐ O eixo começa na primeira hora com caso. Começar às 00h deixava a
  // madrugada sem caso como um vazio largo, e a linha nascia no meio do
  // quadro. As horas vazias DEPOIS do primeiro caso continuam vazias.
  const inicio = todasAsHoras.findIndex((v) => v !== null);
  if (inicio < 0) return null;
  const valores = todasAsHoras.slice(inicio);
  const hora = (i: number) => String(inicio + i).padStart(2, "0");

  const base = ALTURA - PAD_BASE;
  const y = (v: number) => PAD_TOPO + (1 - (v - MIN) / (MAX - MIN)) * (base - PAD_TOPO);
  const util = Math.max(largura - PAD_ESQ - 2, 2);
  const x = (i: number) =>
    PAD_ESQ + (valores.length === 1 ? util / 2 : (i / (valores.length - 1)) * util);

  const todos = valores.map((v, i) => (v === null ? null : { x: x(i), y: y(v), v, i }));
  const pontos = todos.filter((p): p is Ponto => p !== null);
  const partes = trechos(todos);
  const fim = pontos.at(-1)!;
  const alvo = foco === null ? null : (todos[foco] ?? null);

  const aoMover = (ev: React.MouseEvent<SVGSVGElement>) => {
    const r = ev.currentTarget.getBoundingClientRect();
    const px = ev.clientX - r.left;
    let melhor = pontos[0];
    for (const p of pontos) if (Math.abs(p.x - px) < Math.abs(melhor.x - px)) melhor = p;
    setFoco(melhor.i);
  };

  // A primeira hora, as de 5 em 5 e a hora atual, sem marcas encostadas.
  const ultimo = valores.length - 1;
  const marcas = [...Array(ultimo + 1).keys()].filter(
    (i) => i === 0 || i === ultimo || ((inicio + i) % 5 === 0 && i >= 2 && ultimo - i >= 2),
  );

  return (
    <>
      {/* A definição fica no `title` do gráfico inteiro. Um eixo rotulado "%"
          não diz percentual *de quê*, e quem lê a tela de supervisão nem sempre
          é quem desenhou a métrica. */}
      <div className="grafico" ref={wrap} title={ajuda}>
        <svg
          width={largura || undefined}
          height={ALTURA}
          viewBox={`0 0 ${Math.max(largura, 1)} ${ALTURA}`}
          role="img"
          aria-label={`Contenção por hora hoje; a última hora com casos, ${hora(fim.i)}h, teve ${fim.v}%`}
          onMouseMove={aoMover}
          onMouseLeave={() => setFoco(null)}
        >
          {/* grade recessiva: 3 linhas, rotuladas */}
          {[25, 50, 75].map((v) => (
            <g key={v}>
              <line x1={PAD_ESQ} x2={largura} y1={y(v)} y2={y(v)} stroke="var(--hairline)" strokeWidth="1" />
              <text x={0} y={y(v) + 3.5} fill="var(--ink-3)" fontSize="10.5" fontFamily="var(--mono)">
                {v}%
              </text>
            </g>
          ))}

          {partes.map((t) => {
            const linha = t.map((p, i) => `${i ? "L" : "M"}${p.x} ${p.y}`).join(" ");
            return (
              <g key={t[0].i}>
                {t.length > 1 && (
                  <>
                    <path
                      d={`${linha} L${t.at(-1)!.x} ${base} L${t[0].x} ${base} Z`}
                      fill="var(--dado-fill)"
                    />
                    <path
                      d={linha}
                      fill="none"
                      stroke="var(--dado)"
                      strokeWidth="2"
                      strokeLinejoin="round"
                      strokeLinecap="round"
                    />
                  </>
                )}
                {t.length === 1 && (
                  <circle cx={t[0].x} cy={t[0].y} r={4} fill="var(--dado)" stroke="var(--surface)" strokeWidth="2" />
                )}
              </g>
            );
          })}

          <circle cx={fim.x} cy={fim.y} r={5} fill="var(--dado)" stroke="var(--surface)" strokeWidth="2" />
          <text
            x={fim.x - 8}
            y={fim.y - 12}
            textAnchor="end"
            fill="var(--ink)"
            fontSize="12"
            fontWeight="600"
            fontFamily="var(--mono)"
          >
            {fim.v}%
          </text>

          {alvo && (
            <>
              <line
                x1={alvo.x}
                x2={alvo.x}
                y1={0}
                y2={ALTURA}
                stroke="var(--ink-3)"
                strokeWidth="1"
                strokeDasharray="3 3"
              />
              <circle cx={alvo.x} cy={alvo.y} r={4.5} fill="var(--dado)" stroke="var(--surface)" strokeWidth="2" />
            </>
          )}
        </svg>

        {alvo && (
          <div className="dica ver" style={{ left: alvo.x, top: alvo.y - 10 }}>
            {hora(alvo.i)}h · <b>{alvo.v}%</b>
          </div>
        )}
      </div>

      <div className="eixo-x">
        {/* Na posição da hora, não espalhadas por igual: com a hora atual no
            fim, as marcas não são equidistantes. */}
        {marcas.map((i) => (
          <span key={i} style={{ left: x(i) }}>
            {hora(i)}h
          </span>
        ))}
      </div>
    </>
  );
}
