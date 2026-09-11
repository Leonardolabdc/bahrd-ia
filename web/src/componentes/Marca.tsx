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
 */
export function Marca() {
  return (
    <svg
      className="marca-glifo"
      viewBox="0 0 28 28"
      fill="none"
      role="img"
      aria-label="Bahrd"
    >
      {/* O sinal mais distante: arco de um quarto de volta, raio 13. */}
      <path
        d="M8 7a13 13 0 0 1 13 13"
        stroke="currentColor"
        strokeWidth="2.4"
        strokeLinecap="round"
        opacity="0.42"
      />
      {/* O sinal próximo, raio 6,5 — metade do externo, para o espaçamento
          entre os arcos ficar igual ao espaçamento até o ponto. */}
      <path
        d="M8 13.5a6.5 6.5 0 0 1 6.5 6.5"
        stroke="currentColor"
        strokeWidth="2.4"
        strokeLinecap="round"
      />
      {/* O veículo. No acento porque é o único elemento que representa algo
          que se move, e é onde o olho deve cair primeiro. */}
      <circle cx="8" cy="20" r="2.9" fill="var(--accent)" />
    </svg>
  );
}
