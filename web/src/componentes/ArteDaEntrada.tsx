import type { Ref } from "react";
import { Marca } from "./Marca";

/**
 * O mapa do fundo da tela de entrada: uma cidade qualquer, vista de cima, à
 * noite.
 *
 * Tudo em vetor e nada em imagem: o fundo e a grade quase invisível são CSS
 * (`.arte` em `painel.css`), e as ruas são este SVG. Fica nítido em qualquer
 * densidade de tela e não custa requisição nenhuma.
 *
 * **Poucas ruas, finas e tortas.** Sete na vertical e seis na horizontal, com
 * espaçamento irregular e uma curva leve cada uma. Ficam discretas de
 * propósito: o que tem de chamar o olho é a rota.
 *
 * **As ruas se esticam, a espessura não.** O `viewBox` é 1000×1000 com
 * `preserveAspectRatio="none"`, então o desenho ocupa o mapa inteiro em
 * qualquer proporção, e `vector-effect: non-scaling-stroke` (no CSS) mantém
 * cada linha com a espessura em pixels que o CSS deu.
 *
 * No rodapé esquerdo, a assinatura: a marca do Bahrd, o nome, um risco e
 * "Central IA". É a `Marca` do cabeçalho, parada; a que acende fica na coluna
 * do formulário, onde a rota chega.
 *
 * Decorativo: `aria-hidden`, fora da ordem de foco e sem clique. A cidade não
 * existe; não é mapa de lugar nenhum.
 */

type Ponto = { x: number; y: number };

/**
 * Uma curva suave que passa por todos os pontos (Catmull-Rom convertida em
 * Bézier cúbica). Nas pontas, o vizinho que falta é o próprio ponto, e a
 * curva sai e chega na direção do trecho seguinte.
 *
 * A rota (`RotaDaEntrada.tsx`) usa a mesma curva, para andar do mesmo jeito
 * que as ruas.
 */
export function curvaSuave(pontos: Ponto[], casas = 1): string {
  if (pontos.length < 2) return "";
  const f = (n: number) => n.toFixed(casas);
  const p = (i: number) => pontos[Math.min(Math.max(i, 0), pontos.length - 1)];
  let d = `M${f(p(0).x)} ${f(p(0).y)}`;
  for (let i = 0; i < pontos.length - 1; i++) {
    const [a, b, c, e] = [p(i - 1), p(i), p(i + 1), p(i + 2)];
    const c1 = { x: b.x + (c.x - a.x) / 6, y: b.y + (c.y - a.y) / 6 };
    const c2 = { x: c.x - (e.x - b.x) / 6, y: c.y - (e.y - b.y) / 6 };
    d += ` C${f(c1.x)} ${f(c1.y)} ${f(c2.x)} ${f(c2.y)} ${f(c.x)} ${f(c.y)}`;
  }
  return d;
}

/**
 * As ruas, no espaço 0–1000, cada uma pelos pontos por onde passa. Começam e
 * terminam um pouco fora do mapa, para a ponta não aparecer.
 */
const VERTICAIS: [number, number][][] = [
  [[40, -20], [49, 330], [68, 660], [86, 1020]],
  [[194, -20], [202, 300], [197, 640], [206, 1020]],
  [[384, -20], [389, 360], [397, 700], [394, 1020]],
  [[562, -20], [566, 280], [575, 620], [581, 1020]],
  [[702, -20], [709, 380], [716, 680], [729, 1020]],
  [[826, -20], [820, 300], [833, 720], [846, 1020]],
  [[902, -20], [906, 420], [917, 760], [926, 1020]],
];
const HORIZONTAIS: [number, number][][] = [
  [[-20, 46], [320, 52], [700, 40], [1020, 32]],
  [[-20, 177], [330, 180], [660, 183], [1020, 208]],
  [[-20, 413], [390, 444], [705, 386], [1020, 352]],
  [[-20, 640], [300, 628], [640, 648], [1020, 612]],
  [[-20, 880], [360, 873], [700, 866], [1020, 842]],
  [[-20, 974], [420, 969], [1020, 956]],
];

const RUAS = [...VERTICAIS, ...HORIZONTAIS].map((pontos) =>
  curvaSuave(pontos.map(([x, y]) => ({ x, y }))),
);

export function ArteDaEntrada({ ref }: { ref?: Ref<HTMLDivElement> }) {
  return (
    <div className="arte" ref={ref} aria-hidden="true">
      <svg
        className="arte-ruas"
        viewBox="0 0 1000 1000"
        preserveAspectRatio="none"
        focusable="false"
      >
        {RUAS.map((d) => (
          <path key={d} className="arte-rua" d={d} />
        ))}
      </svg>

      <div className="arte-assinatura">
        <span className="arte-assinatura-marca">
          <Marca />
          <span className="arte-assinatura-logo">Bahrd</span>
        </span>
        <span className="arte-assinatura-risco" />
        <span className="arte-assinatura-texto">
          <strong>Central IA</strong>
          <span>Monitoramento e rastreamento 24 h</span>
        </span>
      </div>
    </div>
  );
}
