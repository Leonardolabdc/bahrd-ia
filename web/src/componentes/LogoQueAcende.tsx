import type { Ref } from "react";
import {
  ARCO_GRANDE,
  ARCO_PEQUENO,
  ESPESSURA_DOS_ARCOS,
  OPACIDADE_DO_ARCO_GRANDE,
  PONTO,
  VIEWBOX_DA_MARCA,
} from "./Marca";

/**
 * A marca do Bahrd, grande, acendendo de dentro para fora quando a rota da
 * tela de entrada chega nela: o ponto, depois o arco pequeno, depois o arco
 * grande. É o sinal saindo do veículo, contado pela própria marca.
 *
 * **Não é um redesenho.** Os `path` e o `circle` são os mesmos de `Marca.tsx`,
 * lidos das constantes de lá.
 *
 * **Quatro camadas, cada uma num `<svg>` próprio, empilhadas.** Embaixo, a
 * marca em repouso, igual à do cabeçalho. Por cima, uma camada por parte, no
 * vermelho da marca, cada uma com o próprio brilho, e é isso que deixa acender
 * uma parte de cada vez.
 *
 * ⚠️ O brilho e a animação de opacidade ficam no **elemento HTML** (o `<svg>`
 * de cada camada, que para o CSS é uma caixa como outra qualquer), com
 * `filter: drop-shadow`. Com `filter` e animação de opacidade no mesmo
 * elemento **dentro** do SVG, o Chrome não desenha o brilho. Ver os blocos
 * `logo-*` em `painel.css`.
 *
 * Decorativa: o nome "Bahrd" vem escrito ao lado, em texto. Por isso
 * `aria-hidden` aqui, sem `role="img"`, para o leitor de tela não ler a
 * marca duas vezes.
 */

type Parte = "ponto" | "arco-pequeno" | "arco-grande";

/** Na ordem em que acendem. */
const PARTES: Parte[] = ["ponto", "arco-pequeno", "arco-grande"];

function Desenho({ parte, emRepouso }: { parte: Parte; emRepouso: boolean }) {
  if (parte === "ponto") {
    // Em repouso, o ponto tem o acento, como no cabeçalho; aceso, a cor da
    // camada (`currentColor`), que é o vermelho da marca.
    return (
      <circle
        cx={PONTO.cx}
        cy={PONTO.cy}
        r={PONTO.r}
        fill={emRepouso ? "var(--accent)" : "currentColor"}
      />
    );
  }
  return (
    <path
      d={parte === "arco-grande" ? ARCO_GRANDE : ARCO_PEQUENO}
      stroke="currentColor"
      strokeWidth={ESPESSURA_DOS_ARCOS}
      strokeLinecap="round"
      opacity={emRepouso && parte === "arco-grande" ? OPACIDADE_DO_ARCO_GRANDE : undefined}
    />
  );
}

export function LogoQueAcende({ ref }: { ref?: Ref<HTMLSpanElement> }) {
  return (
    <span className="logo-acende" ref={ref} aria-hidden="true">
      {/* Na ordem de pintura de `Marca.tsx`: o ponto por cima. */}
      <svg className="logo-base" viewBox={VIEWBOX_DA_MARCA} fill="none" focusable="false">
        {[...PARTES].reverse().map((p) => (
          <Desenho key={p} parte={p} emRepouso />
        ))}
      </svg>
      {PARTES.map((p) => (
        <svg
          key={p}
          className={`logo-parte logo-parte-${p}`}
          viewBox={VIEWBOX_DA_MARCA}
          fill="none"
          focusable="false"
        >
          <Desenho parte={p} emRepouso={false} />
        </svg>
      ))}
    </span>
  );
}
