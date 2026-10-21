/**
 * A marca da Bahrd: um ponto e dois arcos.
 *
 * O ponto é o veículo; os arcos são o sinal chegando na central. Eles abrem
 * para cima e para a direita, e não para cima como num ícone de wi-fi, porque
 * a diagonal dá movimento — o que é rastreado está indo para algum lugar.
 *
 * Desenhada em SVG inline, e não como arquivo de imagem, por três motivos:
 * herda `currentColor` e resolve os dois temas sem uma segunda arte; não
 * carrega uma requisição a mais no topo da página; e não vira um arquivo que
 * alguém esquece de atualizar quando a cor muda.
 *
 * O `viewBox` é 28×28 com respiro nas bordas: `stroke-linecap="round"` engorda
 * as pontas em metade da espessura, e sem a folga o arco externo encostaria na
 * caixa em telas de alta densidade.
 *
 * A geometria fica nas constantes abaixo, e não só dentro do JSX, porque a
 * tela de entrada desenha a mesma marca em camadas separadas, uma por parte,
 * para acender uma de cada vez (`LogoQueAcende.tsx`). As duas leem daqui: a
 * marca é uma só, e mudar um arco aqui muda nos dois lugares.
 */

/** O espaço de desenho da marca, em unidades do `viewBox`. */
export const LADO_DA_MARCA = 28;
export const VIEWBOX_DA_MARCA = `0 0 ${LADO_DA_MARCA} ${LADO_DA_MARCA}`;
export const ESPESSURA_DOS_ARCOS = 2.4;

/** O sinal mais distante: arco de um quarto de volta, raio 13. */
export const ARCO_GRANDE = "M8 7a13 13 0 0 1 13 13";
/** Opacidade do arco grande na marca em repouso: o sinal que vai sumindo. */
export const OPACIDADE_DO_ARCO_GRANDE = 0.42;
/** O sinal próximo, raio 6,5 — metade do externo, para o espaçamento entre
 *  os arcos ficar igual ao espaçamento até o ponto. */
export const ARCO_PEQUENO = "M8 13.5a6.5 6.5 0 0 1 6.5 6.5";
/** O veículo. */
export const PONTO = { cx: 8, cy: 20, r: 2.9 } as const;

export function Marca() {
  return (
    <svg
      className="marca-glifo"
      viewBox={VIEWBOX_DA_MARCA}
      fill="none"
      role="img"
      aria-label="Bahrd"
    >
      {/* O sinal mais distante: arco de um quarto de volta, raio 13. */}
      <path
        d={ARCO_GRANDE}
        stroke="currentColor"
        strokeWidth={ESPESSURA_DOS_ARCOS}
        strokeLinecap="round"
        opacity={OPACIDADE_DO_ARCO_GRANDE}
      />
      {/* O sinal próximo, raio 6,5 — metade do externo, para o espaçamento
          entre os arcos ficar igual ao espaçamento até o ponto. */}
      <path
        d={ARCO_PEQUENO}
        stroke="currentColor"
        strokeWidth={ESPESSURA_DOS_ARCOS}
        strokeLinecap="round"
      />
      {/* O veículo. No acento porque é o único elemento que representa algo
          que se move, e é onde o olho deve cair primeiro. */}
      <circle cx={PONTO.cx} cy={PONTO.cy} r={PONTO.r} fill="var(--accent)" />
    </svg>
  );
}
