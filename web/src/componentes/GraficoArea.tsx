import { useEffect, useRef, useState } from "react";

/**
 * Contenção ao longo do dia.
 *
 * Duas decisões de leitura vindas do protótipo, mantidas:
 *  · escala 35–75%, com folga — eixo truncado sem avisar é engano visual;
 *  · rótulo direto só no último ponto, e cinco marcas no eixo x, não vinte.
 */
const MIN = 35;
const MAX = 75;
const ALTURA = 170;
const PAD_TOPO = 14;
const PAD_BASE = 10;

export function GraficoArea({
  valores,
  ajuda,
}: {
  valores: number[];
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

  if (!valores.length) return null;

  const y = (v: number) => PAD_TOPO + (1 - (v - MIN) / (MAX - MIN)) * (ALTURA - PAD_TOPO - PAD_BASE);
  const x = (i: number) => (i / (valores.length - 1)) * (Math.max(largura, 2) - 2) + 1;

  const pontos = valores.map((v, i) => ({ x: x(i), y: y(v), v, i }));
  const linha = pontos.map((p, i) => `${i ? "L" : "M"}${p.x} ${p.y}`).join(" ");
  const area = `${linha} L${pontos.at(-1)!.x} ${ALTURA - PAD_BASE} L${pontos[0].x} ${ALTURA - PAD_BASE} Z`;
  const fim = pontos.at(-1)!;
  const alvo = foco === null ? null : pontos[foco];

  const aoMover = (ev: React.MouseEvent<SVGSVGElement>) => {
    const r = ev.currentTarget.getBoundingClientRect();
    const px = ev.clientX - r.left;
    let melhor = 0;
    pontos.forEach((p, i) => {
      if (Math.abs(p.x - px) < Math.abs(pontos[melhor].x - px)) melhor = i;
    });
    setFoco(melhor);
  };

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
          aria-label={`Contenção por hora, de ${valores[0]}% às 00h a ${fim.v}% às ${valores.length - 1}h`}
          onMouseMove={aoMover}
          onMouseLeave={() => setFoco(null)}
        >
          {/* grade recessiva: 3 linhas, rotuladas */}
          {[40, 55, 70].map((v) => (
            <g key={v}>
              <line x1={0} x2={largura} y1={y(v)} y2={y(v)} stroke="var(--hairline)" strokeWidth="1" />
              <text x={2} y={y(v) - 5} fill="var(--ink-3)" fontSize="10.5" fontFamily="var(--mono)">
                {v}%
              </text>
            </g>
          ))}

          <path d={area} fill="var(--dado-fill)" />
          <path
            d={linha}
            fill="none"
            stroke="var(--dado)"
            strokeWidth="2"
            strokeLinejoin="round"
            strokeLinecap="round"
          />

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
            {String(alvo.i).padStart(2, "0")}h · <b>{alvo.v}%</b>
          </div>
        )}
      </div>

      <div className="eixo-x">
        {[0, 5, 10, 15, valores.length - 1].map((i) => (
          <span key={i}>{String(i).padStart(2, "0")}h</span>
        ))}
      </div>
    </>
  );
}
