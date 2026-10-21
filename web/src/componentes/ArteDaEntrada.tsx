import type { Ref } from "react";

/**
 * O mapa do fundo da tela de entrada: um bairro qualquer, visto de cima.
 *
 * Tudo em vetor e nada em imagem: o degradê e a grade de 40 px são CSS
 * (`.arte` em `painel.css`), e as ruas são este SVG. Fica nítido em qualquer
 * densidade de tela e não custa requisição nenhuma.
 *
 * **As ruas se esticam, a espessura não.** O `viewBox` é 1000×1000 com
 * `preserveAspectRatio="none"`, então o desenho ocupa o mapa inteiro em
 * qualquer proporção, e `vector-effect: non-scaling-stroke` (no CSS) mantém
 * cada linha com a espessura em pixels que o CSS deu. As posições das ruas
 * principais são frações da largura e da altura, exportadas abaixo, e é por
 * elas que a rota (`RotaDaEntrada.tsx`) anda: ela cai em cima das ruas em
 * qualquer tamanho de janela.
 *
 * Decorativo: `aria-hidden`, fora da ordem de foco e sem clique. O bairro não
 * existe; não é mapa de lugar nenhum.
 */

/** As ruas principais, em fração da largura (verticais) e da altura (horizontais). */
export const RUAS_VERTICAIS = [0.07, 0.21, 0.37, 0.53, 0.69, 0.85] as const;
export const RUAS_HORIZONTAIS = [0.13, 0.29, 0.46, 0.63, 0.81] as const;

/** Ruas menores, em trechos, no espaço 0–1000: quebram a grade regular. */
const RUAS_MENORES = [
  "M140 290V630",
  "M290 0V460",
  "M450 0V130",
  "M450 460V1000",
  "M610 130V630",
  "M770 630V1000",
  "M930 0V460",
  "M210 210H690",
  "M0 375H530",
  "M370 545H1000",
  "M0 720H370",
  "M690 720H1000",
  "M210 900H850",
  "M530 60H1000",
];

/** Avenidas: as que cortam o bairro na diagonal e em curva. */
const AVENIDAS = [
  "M0 960C180 820 300 760 420 700S760 520 1000 300",
  "M600 1000L1000 650",
  "M-40 430Q120 90 520 -40",
];

/** Um rio no canto, para o mapa não ser só grade. */
const RIO = "M-20 250C120 230 190 120 300 60S430 -10 540 -40";

/** Duas quadras de praça. */
const PRACAS = [
  { x: 378, y: 138, largura: 144, altura: 144 },
  { x: 698, y: 638, largura: 144, altura: 164 },
];

const escala = (fracao: number) => fracao * 1000;

export function ArteDaEntrada({ ref }: { ref?: Ref<HTMLDivElement> }) {
  return (
    <div className="arte" ref={ref} aria-hidden="true">
      <svg
        className="arte-ruas"
        viewBox="0 0 1000 1000"
        preserveAspectRatio="none"
        focusable="false"
      >
        {PRACAS.map((p) => (
          <rect
            key={`${p.x}-${p.y}`}
            className="arte-praca"
            x={p.x}
            y={p.y}
            width={p.largura}
            height={p.altura}
          />
        ))}
        <path className="arte-rio" d={RIO} />
        {RUAS_MENORES.map((d) => (
          <path key={d} className="arte-rua" d={d} />
        ))}
        {AVENIDAS.map((d) => (
          <path key={d} className="arte-avenida" d={d} />
        ))}
        {RUAS_VERTICAIS.map((x) => (
          <path key={`v${x}`} className="arte-rua-principal" d={`M${escala(x)} 0V1000`} />
        ))}
        {RUAS_HORIZONTAIS.map((y) => (
          <path key={`h${y}`} className="arte-rua-principal" d={`M0 ${escala(y)}H1000`} />
        ))}
      </svg>
    </div>
  );
}
