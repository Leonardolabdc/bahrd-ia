import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type RefObject,
} from "react";
import { LADO_DA_MARCA, PONTO } from "./Marca";
import { RUAS_HORIZONTAIS, RUAS_VERTICAIS } from "./ArteDaEntrada";

/**
 * A rota da tela de entrada: um veículo anda pelas ruas do mapa, e o sinal
 * dele chega à marca do Bahrd, que acende. É o que a Central faz o dia
 * inteiro, contado em dezoito segundos.
 *
 * **Calculada em pixels, a partir do tamanho real.** Um `ResizeObserver` mede
 * o mapa e o bloco do formulário, e a rota é refeita sempre que um dos dois
 * muda de tamanho (a janela, a fonte que carregou, a mensagem de erro que
 * empurrou o formulário). Ela anda pelas ruas principais de `ArteDaEntrada`,
 * que são frações do mapa, e termina **na borda direita do mapa, na altura
 * do ponto da marca**: é ali, na linha que separa o mapa do formulário, que o
 * sinal encosta e cintila para cima e para baixo.
 *
 * **A estrada e o rastro.** A rota inteira fica sempre desenhada, bem apagada,
 * como estrada. O que acende é só o rastro atrás do veículo: forte colado
 * nele e sumindo para trás. Ver `pintarRastro`.
 *
 * O SVG cobre a tela de entrada inteira, e não só o mapa, para usar o mesmo
 * sistema de coordenadas da cintilada da divisa, que é HTML. Não pega clique
 * nem foco (`pointer-events: none` no CSS).
 *
 * **Os tempos moram no CSS** (blocos `rota-*` e `entrada-*` de `painel.css`),
 * todos no mesmo ciclo de 18 s. As frações de `PINOS` e `ETIQUETAS` aparecem
 * lá também, convertidas em momento do ciclo: o veículo anda em velocidade
 * constante de 0 a 55%, então a fração `f` do comprimento é alcançada em
 * `f × 55%`. Mudou uma fração aqui, muda o keyframe correspondente lá. O
 * rastro não tem keyframe: ele lê o relógio da animação do veículo.
 *
 * Todos os valores das etiquetas são inventados: não há cliente, veículo nem
 * coordenada de verdade nesta tela.
 */

type Ponto = { x: number; y: number };
type Caixa = { x: number; y: number; largura: number; altura: number };

/** Onde ficam os pinos, em fração do comprimento da rota. */
const PINOS = [0.24, 0.47, 0.68] as const;

/** Em que momento do ciclo o veículo chega à borda do mapa (`entrada-veiculo`). */
const CHEGADA_NO_CICLO = 0.55;

/** Em quantos pedaços o rastro é dividido, todos do mesmo comprimento. */
const PEDACOS_DO_RASTRO = 260;

/** O comprimento do rastro, em fração da rota. */
const CAUDA = 0.38;

/** A opacidade do rastro colado no veículo, e a curva com que ela cai. */
const OPACIDADE_NA_PONTA = 0.9;
const CURVA_DA_CAUDA = 1.6;

/** Até onde a cintilada da divisa vai, em fração da distância até a borda. */
const ALCANCE_DA_CINTILADA = 0.85;

/** A largura da faixa que leva a cintilada, centrada na linha: folga para o
 *  `drop-shadow` dos brilhos não ser cortado dos lados. */
const LARGURA_DA_DIVISA = 40;

type Etiqueta = {
  id: string;
  chave: string;
  valor: string;
  fracao: number;
  /** Lado preferido. BAT vai abaixo da linha para não cobri-la; se ali ela
   *  encostar na rota, tenta os outros lados (`caixaDaEtiqueta`). */
  lado: "acima" | "abaixo";
};

const ETIQUETAS: Etiqueta[] = [
  { id: "evento", chave: "EVENTO", valor: "DEMO-0001", fracao: 0.04, lado: "acima" },
  { id: "gps", chave: "GPS", valor: "12,3456 S · 45,6789 O", fracao: 0.33, lado: "acima" },
  { id: "ign", chave: "IGN", valor: "LIGADA", fracao: 0.56, lado: "acima" },
  { id: "bat", chave: "BAT", valor: "12,6 V", fracao: 0.74, lado: "abaixo" },
];

/** Largura de um caractere da fonte mono a 10,5 px, com folga. A etiqueta é
 *  medida por conta, e não pelo DOM, para não custar uma segunda medição. */
const LARGURA_DO_CARACTERE = 6.7;
const ALTURA_DA_ETIQUETA = 20;
const RESPIRO_DA_ETIQUETA = 8;

/** Raio das esquinas da rota, em px. */
const RAIO_DA_ESQUINA = 16;

type Geometria = {
  largura: number;
  altura: number;
  mapa: Caixa;
  /** Onde a rota termina: a borda direita do mapa, na altura do ponto da marca. */
  chegada: Ponto;
};

type Marcos = {
  pinos: Ponto[];
  etiquetas: { ponto: Ponto; caixa: Caixa; ancora: Ponto; cabe: boolean }[];
};

const arredonda = (n: number) => Math.round(n * 2) / 2;
const fixo = (n: number) => n.toFixed(1);
const distancia = (a: Ponto, b: Ponto) => Math.hypot(b.x - a.x, b.y - a.y);
const limita = (n: number, min: number, max: number) =>
  max < min ? (min + max) / 2 : Math.min(Math.max(n, min), max);

/** Linhas retas com as esquinas arredondadas: rua tem curva, não quina. */
function caminhoArredondado(pontos: Ponto[], raio: number): string {
  const p: Ponto[] = [];
  for (const ponto of pontos) {
    if (p.length === 0 || distancia(p[p.length - 1], ponto) > 0.5) p.push(ponto);
  }
  if (p.length < 2) return "";

  let d = `M${fixo(p[0].x)} ${fixo(p[0].y)}`;
  for (let i = 1; i < p.length - 1; i++) {
    const [a, b, c] = [p[i - 1], p[i], p[i + 1]];
    const l1 = distancia(a, b);
    const l2 = distancia(b, c);
    const r = Math.min(raio, l1 / 2, l2 / 2);
    const entra = { x: b.x + ((a.x - b.x) * r) / l1, y: b.y + ((a.y - b.y) * r) / l1 };
    const sai = { x: b.x + ((c.x - b.x) * r) / l2, y: b.y + ((c.y - b.y) * r) / l2 };
    d += ` L${fixo(entra.x)} ${fixo(entra.y)} Q${fixo(b.x)} ${fixo(b.y)} ${fixo(sai.x)} ${fixo(sai.y)}`;
  }
  const fim = p[p.length - 1];
  return `${d} L${fixo(fim.x)} ${fixo(fim.y)}`;
}

/**
 * O trajeto, em ruas: sobe, vira, sobe, vira, e no fim sobe (ou desce) pela
 * última rua até a altura da marca e sai pela borda do mapa.
 */
function tracado(g: Geometria): string {
  const { mapa, chegada } = g;
  const em = (fx: number, fy: number): Ponto => ({
    x: mapa.x + fx * mapa.largura,
    y: mapa.y + fy * mapa.altura,
  });
  const [, x1, , x3, , x5] = RUAS_VERTICAIS;
  const [, , y2, y3, y4] = RUAS_HORIZONTAIS;
  const ultimaRua = em(x5, y2).x;
  return caminhoArredondado(
    [
      em(x1, y4),
      em(x1, y3),
      em(x3, y3),
      em(x3, y2),
      em(x5, y2),
      { x: ultimaRua, y: chegada.y },
      chegada,
    ],
    RAIO_DA_ESQUINA,
  );
}

type Pedaco = {
  /** O grupo do pedaço: o `stroke-opacity` dele vale para o brilho e o traço. */
  el: SVGGElement;
  /** O meio do pedaço, em fração da rota. */
  meio: number;
  /** Metade do comprimento do pedaço, em fração da rota. */
  meia: number;
  /** A opacidade escrita por último, para não mexer no DOM à toa. */
  atual: number;
};

const SVG = "http://www.w3.org/2000/svg";

/**
 * Corta a rota em `PEDACOS_DO_RASTRO` pedaços do mesmo comprimento, cada um
 * com a própria opacidade. É o que deixa o degradê do rastro contínuo: camadas
 * empilhadas ou um traço com várias opacidades mostram degraus.
 *
 * Cada pedaço segue a curva (pontos tirados com `getPointAtLength`) e tem
 * ponta reta, porque a redonda sobrepõe o vizinho e a transparência soma na
 * emenda. Para as pontas retas de dois vizinhos se encaixarem nas esquinas,
 * cada pedaço começa e termina com um passo minúsculo na direção da própria
 * rota: a ponta reta fica perpendicular à rota ali, a mesma nos dois lados.
 *
 * Os elementos são criados aqui, fora do React: são centenas, mudam de
 * opacidade a cada quadro, e um re-render por quadro custaria caro.
 */
function montarRastro(grupo: SVGGElement, caminho: SVGPathElement): Pedaco[] {
  grupo.replaceChildren();
  const total = caminho.getTotalLength();
  if (!total) return [];
  const passo = total / PEDACOS_DO_RASTRO;
  const tangente = Math.min(0.3, passo / 4);
  const em = (s: number) => {
    const q = caminho.getPointAtLength(limita(s, 0, total));
    return `${q.x.toFixed(2)} ${q.y.toFixed(2)}`;
  };
  const fragmento = document.createDocumentFragment();
  const pedacos: Pedaco[] = [];
  for (let k = 0; k < PEDACOS_DO_RASTRO; k++) {
    const inicio = k * passo;
    const fim = (k + 1) * passo;
    const d =
      `M${em(inicio)}L${em(inicio + tangente)}L${em(inicio + passo / 2)}` +
      `L${em(fim - tangente)}L${em(fim)}`;
    const el = document.createElementNS(SVG, "g");
    el.setAttribute("stroke-opacity", "0");
    for (const classe of ["rota-rastro-brilho", "rota-rastro-traco"]) {
      const p = document.createElementNS(SVG, "path");
      p.setAttribute("class", classe);
      p.setAttribute("d", d);
      el.appendChild(p);
    }
    fragmento.appendChild(el);
    pedacos.push({ el, meio: (inicio + passo / 2) / total, meia: passo / 2 / total, atual: 0 });
  }
  grupo.appendChild(fragmento);
  return pedacos;
}

/**
 * Acende cada pedaço pela distância até a ponta do rastro: 0,9 colado no
 * veículo, caindo em (1 − d/L)^1,6 até zero a `CAUDA` de distância.
 *
 * `ponta` é a fração da rota onde o veículo está, e passa de 1 depois que ele
 * chega à borda: a cauda continua andando e entra na borda até sumir, sem
 * deixar pedaço aceso parado no fim da rota. Na volta do ciclo, `ponta` cai
 * para 0 e tudo apaga.
 */
function pintarRastro(pedacos: Pedaco[], ponta: number) {
  for (const p of pedacos) {
    const atras = ponta - p.meio;
    let o = 0;
    // O pedaço debaixo do veículo já acende; os da frente, não.
    if (atras > -p.meia && atras < CAUDA) {
      o = OPACIDADE_NA_PONTA * (1 - Math.max(atras, 0) / CAUDA) ** CURVA_DA_CAUDA;
    }
    o = Math.round(o * 1000) / 1000;
    if (o !== p.atual) {
      p.atual = o;
      p.el.setAttribute("stroke-opacity", String(o));
    }
  }
}

function apagarRastro(pedacos: Pedaco[]) {
  pintarRastro(pedacos, -1);
}

type Lado = "acima" | "abaixo" | "direita" | "esquerda";

/** Em que ordem tentar cada lado. BAT começa por baixo, como pede o desenho. */
const PREFERENCIA: Record<Etiqueta["lado"], Lado[]> = {
  acima: ["acima", "direita", "esquerda", "abaixo"],
  abaixo: ["abaixo", "esquerda", "direita", "acima"],
};

const encosta = (c: Caixa, p: Ponto, folga: number) =>
  p.x >= c.x - folga && p.x <= c.x + c.largura + folga &&
  p.y >= c.y - folga && p.y <= c.y + c.altura + folga;

const cruza = (a: Caixa, b: Caixa, folga: number) =>
  a.x < b.x + b.largura + folga && b.x < a.x + a.largura + folga &&
  a.y < b.y + b.altura + folga && b.y < a.y + a.altura + folga;

/**
 * Onde a etiqueta fica: no primeiro lado, na ordem de preferência, em que ela
 * não encosta na linha, nem num pino, nem numa etiqueta já posta.
 *
 * Por colisão, e não pela direção da rota no ponto: perto de uma esquina a
 * direção engana (o trecho é horizontal, mas a amostra pega a curva), e a
 * etiqueta caía em cima da linha. Tenta cada lado perto e, depois, mais longe.
 * Se nenhum servir (mapa estreito, perto dos 900 px), a etiqueta não aparece:
 * cobrir a linha é justamente o que ela não pode fazer.
 */
function caixaDaEtiqueta(
  e: Etiqueta,
  ponto: Ponto,
  mapa: Caixa,
  rota: Ponto[],
  pinos: Ponto[],
  postas: Caixa[],
): { caixa: Caixa; ancora: Ponto; cabe: boolean } {
  const largura = (e.chave.length + 1 + e.valor.length) * LARGURA_DO_CARACTERE + 2 * RESPIRO_DA_ETIQUETA;
  const altura = ALTURA_DA_ETIQUETA;
  const centro = (lado: Lado, longe: number): Ponto => {
    switch (lado) {
      case "acima": return { x: ponto.x, y: ponto.y - 26 - longe };
      case "abaixo": return { x: ponto.x, y: ponto.y + 26 + longe };
      case "direita": return { x: ponto.x + 18 + longe + largura / 2, y: ponto.y };
      case "esquerda": return { x: ponto.x - 18 - longe - largura / 2, y: ponto.y };
    }
  };
  const caixaEm = (lado: Lado, longe = 0): Caixa => {
    const c = centro(lado, longe);
    const cx = limita(c.x, mapa.x + largura / 2 + 10, mapa.x + mapa.largura - largura / 2 - 10);
    const cy = limita(c.y, mapa.y + altura / 2 + 10, mapa.y + mapa.altura - altura / 2 - 10);
    return { x: cx - largura / 2, y: cy - altura / 2, largura, altura };
  };
  const livre = (c: Caixa) =>
    !rota.some((p) => encosta(c, p, 5)) &&
    // O pulso chega a ~23 px do centro, e o radar do terceiro pino a 26.
    !pinos.some((p, i) => encosta(c, p, i === 2 ? 28 : 14)) &&
    !postas.some((outra) => cruza(c, outra, 6));

  const lados = PREFERENCIA[e.lado];
  const candidatas = [0, 22].flatMap((longe) => lados.map((lado) => caixaEm(lado, longe)));
  const achada = candidatas.find(livre);
  const caixa = achada ?? caixaEm(lados[0]);
  // O fio sai do ponto da rota e encosta na borda mais próxima da etiqueta.
  const ancora = {
    x: limita(ponto.x, caixa.x, caixa.x + largura),
    y: limita(ponto.y, caixa.y, caixa.y + altura),
  };
  return { caixa, ancora, cabe: achada !== undefined };
}

function medir(
  raiz: HTMLElement,
  mapa: HTMLElement,
  marca: HTMLElement,
): Geometria | null {
  const r = raiz.getBoundingClientRect();
  const m = mapa.getBoundingClientRect();
  const a = marca.getBoundingClientRect();
  if (m.width < 40 || m.height < 40 || a.width === 0) return null;

  const caixaDoMapa = {
    x: arredonda(m.left - r.left),
    y: arredonda(m.top - r.top),
    largura: arredonda(m.width),
    altura: arredonda(m.height),
  };
  // A altura do ponto da marca, e não do meio da caixa: é no veículo que o
  // sinal chega, e é dele que a marca acende para fora.
  const escala = a.height / LADO_DA_MARCA;
  const yDoPonto = a.top - r.top + PONTO.cy * escala;
  const y = limita(yDoPonto, caixaDoMapa.y + 24, caixaDoMapa.y + caixaDoMapa.altura - 24);
  return {
    largura: arredonda(r.width),
    altura: arredonda(r.height),
    mapa: caixaDoMapa,
    chegada: { x: caixaDoMapa.x + caixaDoMapa.largura, y: arredonda(y) },
  };
}

const mesmaGeometria = (a: Geometria | null, b: Geometria | null) =>
  JSON.stringify(a) === JSON.stringify(b);

/**
 * Põe todas as animações da tela de entrada no mesmo relógio.
 *
 * Cada animação de CSS começa quando o elemento ganha o estilo. A marca nasce
 * junto com a tela, mas a rota some e volta quando a janela passa dos 900 px
 * (`display: none` cancela a animação, e voltar a mostra recomeça do zero), e
 * aí a rota chegaria à marca fora de hora. Alinhar todas ao começo do relógio
 * do documento (`startTime = 0`) põe todas na mesma fase, sempre. Funciona
 * porque todo período aqui divide os 18 s do ciclo: pulso de 2 s, radar de 3 s.
 *
 * Só as animações com o prefixo `entrada-`: a chegada do formulário é outra
 * coisa e não pode ser pulada.
 */
export function useCicloDaEntrada(raiz: RefObject<HTMLElement | null>) {
  useEffect(() => {
    let quadro = 0;
    const alinhar = () => {
      cancelAnimationFrame(quadro);
      quadro = requestAnimationFrame(() => {
        const el = raiz.current;
        if (!el || typeof el.getAnimations !== "function" || typeof CSSAnimation === "undefined") {
          return;
        }
        for (const animacao of el.getAnimations({ subtree: true })) {
          if (animacao instanceof CSSAnimation && animacao.animationName.startsWith("entrada-")) {
            animacao.startTime = 0;
          }
        }
      });
    };
    alinhar();
    const consultas = ["(max-width: 900px)", "(prefers-reduced-motion: reduce)"].map((q) =>
      window.matchMedia(q),
    );
    consultas.forEach((c) => c.addEventListener("change", alinhar));
    return () => {
      cancelAnimationFrame(quadro);
      consultas.forEach((c) => c.removeEventListener("change", alinhar));
    };
  }, [raiz]);
}

export function RotaDaEntrada({
  raiz,
  mapa,
  marca,
  conteudo,
}: {
  /** A tela de entrada inteira: é o sistema de coordenadas do SVG. */
  raiz: RefObject<HTMLElement | null>;
  mapa: RefObject<HTMLElement | null>;
  /** A marca que acende, onde a rota chega. */
  marca: RefObject<HTMLElement | null>;
  /** O bloco da marca e do formulário: quando ele cresce, a marca se mexe. */
  conteudo: RefObject<HTMLElement | null>;
}) {
  const [geo, setGeo] = useState<Geometria | null>(null);
  const [marcos, setMarcos] = useState<Marcos | null>(null);
  const svg = useRef<SVGSVGElement>(null);
  const medidor = useRef<SVGPathElement>(null);
  const rastro = useRef<SVGGElement>(null);
  const pedacos = useRef<Pedaco[]>([]);
  const veiculo = useRef<SVGPathElement>(null);

  // `useEffect`, e não `useLayoutEffect`: este componente vem antes da coluna
  // do formulário na árvore, e no efeito de layout dele as refs da marca e do
  // conteúdo ainda não estão ligadas. Sem elas o conteúdo não era observado, e
  // a rota ficava na altura antiga quando o selo de ambiente chegava e
  // empurrava a marca. Até a primeira medida o SVG fica escondido
  // (`rota-sem-medida`), então não há quadro com a rota no lugar errado.
  useEffect(() => {
    const atualizar = () => {
      const r = raiz.current;
      const m = mapa.current;
      const a = marca.current;
      // Até 900 px a rota não aparece (CSS): não há o que medir.
      if (!r || !m || !a || !svg.current || getComputedStyle(svg.current).display === "none") {
        return;
      }
      const nova = medir(r, m, a);
      setGeo((atual) => (mesmaGeometria(atual, nova) ? atual : nova));
    };
    atualizar();
    const observador = new ResizeObserver(atualizar);
    for (const el of [raiz.current, mapa.current, marca.current, conteudo.current]) {
      if (el) observador.observe(el);
    }
    return () => observador.disconnect();
  }, [raiz, mapa, marca, conteudo]);

  const d = useMemo(() => (geo ? tracado(geo) : ""), [geo]);

  // Pinos e etiquetas na rota de verdade, já com as curvas das esquinas. A
  // medida é feita num caminho sem `pathLength`: com ele, alguns navegadores
  // escalam a distância de `getPointAtLength` e outros não.
  useLayoutEffect(() => {
    const caminho = medidor.current;
    if (!caminho || !geo || !d) return;
    const total = caminho.getTotalLength();
    if (!total) return;
    const em = (f: number): Ponto => {
      const q = caminho.getPointAtLength(f * total);
      return { x: q.x, y: q.y };
    };
    // A linha amostrada a cada ~6 px, para as etiquetas saberem onde ela passa.
    const amostras = Math.max(2, Math.ceil(total / 6));
    const rota = Array.from({ length: amostras + 1 }, (_, k) => em(k / amostras));
    const pinos = PINOS.map(em);
    const postas: Caixa[] = [];
    setMarcos({
      pinos,
      etiquetas: ETIQUETAS.map((e) => {
        const ponto = em(e.fracao);
        const posta = caixaDaEtiqueta(e, ponto, geo.mapa, rota, pinos, postas);
        if (posta.cabe) postas.push(posta.caixa);
        return { ponto, ...posta };
      }),
    });
  }, [d, geo]);

  // Os pedaços do rastro, refeitos sempre que a rota muda. Apagados até o
  // próximo quadro do rastro acender os certos.
  useLayoutEffect(() => {
    const grupo = rastro.current;
    const caminho = medidor.current;
    if (!grupo) return;
    if (caminho && d) {
      pedacos.current = montarRastro(grupo, caminho);
    } else {
      grupo.replaceChildren();
      pedacos.current = [];
    }
  }, [d]);

  // O rastro anda no relógio da animação de CSS do veículo
  // (`entrada-veiculo`), e não num relógio próprio: assim ele fica colado no
  // ponto mesmo depois que `useCicloDaEntrada` realinha as animações. A cada
  // quadro, lê o progresso do ciclo (0 a 1) e muda só atributos, sem passar
  // pelo React.
  //
  // O laço para quando não há o que mostrar: a aba oculta, quem pediu menos
  // movimento, a tela estreita (a rota some até 900 px) e, claro, quando a
  // tela de entrada sai, na desmontagem.
  useEffect(() => {
    const semMovimento = window.matchMedia("(prefers-reduced-motion: reduce)");
    const estreita = window.matchMedia("(max-width: 900px)");
    let quadro = 0;
    let animacao: Animation | null = null;

    const progresso = (): number | null => {
      const el = veiculo.current;
      if (!el || typeof el.getAnimations !== "function") return null;
      if (!animacao || animacao.playState === "idle") {
        const todas = el.getAnimations();
        const temNome = typeof CSSAnimation !== "undefined";
        animacao =
          todas.find(
            (a) => temNome && a instanceof CSSAnimation && a.animationName === "entrada-veiculo",
          ) ??
          todas[0] ??
          null;
      }
      const p = animacao?.effect?.getComputedTiming().progress;
      return typeof p === "number" ? p : null;
    };

    const desenhar = () => {
      quadro = requestAnimationFrame(desenhar);
      const p = progresso();
      if (p === null) {
        animacao = null;
        apagarRastro(pedacos.current);
        return;
      }
      pintarRastro(pedacos.current, p / CHEGADA_NO_CICLO);
    };

    const ligar = () => {
      cancelAnimationFrame(quadro);
      quadro = 0;
      animacao = null;
      if (document.hidden || semMovimento.matches || estreita.matches) {
        apagarRastro(pedacos.current);
        return;
      }
      quadro = requestAnimationFrame(desenhar);
    };

    ligar();
    document.addEventListener("visibilitychange", ligar);
    semMovimento.addEventListener("change", ligar);
    estreita.addEventListener("change", ligar);
    return () => {
      cancelAnimationFrame(quadro);
      document.removeEventListener("visibilitychange", ligar);
      semMovimento.removeEventListener("change", ligar);
      estreita.removeEventListener("change", ligar);
    };
  }, []);

  // Os elementos existem desde a primeira pintura, mesmo antes da medida, e
  // nunca são recriados: uma animação de CSS recomeça quando o elemento nasce,
  // e um pino recriado a cada redimensionamento sairia do compasso.
  const fora: Ponto = { x: -100, y: -100 };
  const largura = geo?.largura ?? 0;
  const altura = geo?.altura ?? 0;

  // A cintilada da divisa: uma faixa estreita em cima da linha entre o mapa e
  // a coluna, da altura do mapa, que corta os brilhos na borda da tela. As
  // distâncias vão em variáveis de CSS, e o `transform` do keyframe as lê.
  // O brilho de 2 px fica centrado na borda do mapa: um pixel no mapa e um na
  // linha. Todo na linha, no tema claro ele seria branco sobre quase branco.
  const divisa: CSSProperties = geo
    ? ({
        left: `${geo.chegada.x - LARGURA_DA_DIVISA / 2}px`,
        top: `${geo.mapa.y}px`,
        height: `${geo.mapa.altura}px`,
        "--contato": `${geo.chegada.y - geo.mapa.y}px`,
        "--subida": `${fixo(ALCANCE_DA_CINTILADA * (geo.chegada.y - geo.mapa.y))}px`,
        "--descida": `${fixo(ALCANCE_DA_CINTILADA * (geo.mapa.y + geo.mapa.altura - geo.chegada.y))}px`,
      } as CSSProperties)
    : {};

  return (
    <>
      <svg
        ref={svg}
        className={`rota${geo && marcos ? "" : " rota-sem-medida"}`}
        width={largura}
        height={altura}
        viewBox={`0 0 ${largura} ${altura}`}
        aria-hidden="true"
        focusable="false"
      >
        <path ref={medidor} className="rota-medida" d={d} />

        {/* A estrada: a rota inteira, apagada, sempre lá. */}
        <path className="rota-estrada" d={d} />

        {/* O rastro: os pedaços nascem em `montarRastro`, fora do React. */}
        <g ref={rastro} className="rota-rastro" />

        <g className="rota-some">
          {PINOS.map((_, i) => {
            const p = marcos?.pinos[i] ?? fora;
            return (
              <g key={i} transform={`translate(${fixo(p.x)} ${fixo(p.y)})`}>
                <g className={`rota-pino rota-pino-${i + 1}`}>
                  {i === 2 && (
                    <g className="rota-radar">
                      <circle className="rota-radar-anel" r={26} />
                      <path className="rota-radar-feixe" d="M0 0L26 0A26 26 0 0 0 13 -22.5Z" />
                    </g>
                  )}
                  <circle className="rota-pulso" r={9} />
                  <circle className="rota-pino-miolo" r={5} />
                </g>
              </g>
            );
          })}

          {ETIQUETAS.map((e, i) => {
            const m = marcos?.etiquetas[i];
            const caixa = m?.caixa ?? { ...fora, largura: 0, altura: ALTURA_DA_ETIQUETA };
            const ponto = m?.ponto ?? fora;
            const ancora = m?.ancora ?? fora;
            return (
              <g
                key={e.id}
                className={`rota-etiqueta rota-etiqueta-${e.id}`}
                visibility={m && !m.cabe ? "hidden" : undefined}
              >
                <line
                  className="rota-etiqueta-fio"
                  x1={fixo(ponto.x)}
                  y1={fixo(ponto.y)}
                  x2={fixo(ancora.x)}
                  y2={fixo(ancora.y)}
                />
                <g transform={`translate(${fixo(caixa.x)} ${fixo(caixa.y)})`}>
                  <rect
                    className="rota-etiqueta-caixa"
                    width={fixo(caixa.largura)}
                    height={caixa.altura}
                    rx={4}
                  />
                  <text className="rota-etiqueta-texto" x={RESPIRO_DA_ETIQUETA} y={13.6}>
                    <tspan className="rota-etiqueta-chave">{e.chave}</tspan> {e.valor}
                  </text>
                </g>
              </g>
            );
          })}
        </g>

        {/* O veículo: um traço de comprimento zero com ponta redonda, que anda
            pelo caminho em velocidade constante. É o relógio do rastro. */}
        <g className="rota-veiculo">
          <path className="rota-veiculo-brilho" d={d} pathLength={100} />
          <path ref={veiculo} className="rota-veiculo-miolo" d={d} pathLength={100} />
        </g>
      </svg>

      {/* A cintilada na linha entre o mapa e a coluna: dois brilhos saem do
          ponto onde o veículo encosta, um subindo e outro descendo. Em HTML,
          e não no SVG: um filtro de SVG em unidades de % não desenha numa
          linha vertical de largura zero, e o `drop-shadow` do CSS desenha. */}
      <div
        className={`rota-divisa${geo ? "" : " rota-sem-medida"}`}
        style={divisa}
        aria-hidden="true"
      >
        <span className="rota-divisa-brilho rota-divisa-sobe" />
        <span className="rota-divisa-brilho rota-divisa-desce" />
      </div>
    </>
  );
}
