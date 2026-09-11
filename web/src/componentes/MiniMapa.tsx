import { useEffect, useMemo, useRef, useState } from "react";

/**
 * Mini-mapa da posição do veículo, no cabeçalho da ocorrência.
 *
 * **Cartografia real, desde 04/09/2026.** Antes daqui havia um desenho: um
 * traçado de ruas gerado a partir da coordenada, com a etiqueta "esboço" em
 * cima para avisar que não era mapa. Agora são tiles de cartografia de
 * verdade, e o operador vê a rua que existe mesmo.
 *
 * **Por que dá para fazer de graça.** Os tiles são imagens públicas e sem
 * chave de API: o navegador do operador baixa `{z}/{y}/{x}` e nós só
 * calculamos qual imagem pedir e onde encaixá-la. Nenhuma biblioteca de mapa
 * entra no pacote, nenhum provedor precisa ser contratado, e o servidor não
 * intermedeia nada.
 *
 * ⛔ **Não é o OpenStreetMap, e a tentativa está registrada aqui de propósito.**
 * O `tile.openstreetmap.org` era a escolha óbvia e foi medida em 04/09/2026:
 * ela devolve `200` com uma imagem escrita "Access blocked — app is not
 * following the tile usage policy" e, na sequência, `429 Access denied` por
 * IP. Os tiles do OSM são mantidos por voluntários e a política deles é
 * restritiva de verdade. **Não voltar a apontar para lá** sem antes servir
 * tile próprio ou passar por um cache nosso com `User-Agent` identificado.
 * O basemap da Carto também foi medido: devolve mapa de verdade com
 * "API KEY REQUIRED" escrito por cima.
 *
 * ⚠️ **O que isso custa em privacidade.** O pedido do tile sai do navegador do
 * operador para um terceiro e leva, no próprio caminho da URL, o quadrado do
 * mundo que está sendo olhado — ou seja, a posição aproximada do caminhão de um
 * cliente, mais o endereço do nosso painel no `Referer`. Para uma POC interna
 * isso é aceitável; se a Bahrd decidir que posição de cliente não pode tocar
 * terceiro, a saída é a mesma de cima — proxy nosso com cache — e só a
 * constante `TILE` muda.
 *
 * O botão "Abrir no Google Maps" continua indo à coordenada real numa aba
 * nova: é onde o operador mede distância e traça rota, o que aqui não se faz.
 */

/**
 * De onde vem a imagem. Sem chave, sem conta, sem SDK.
 *
 * O basemap de ruas da Esri, que responde sem chave e traz nome de rua em
 * português. Note a ordem: aqui é `{z}/{y}/{x}`, com a linha antes da coluna,
 * ao contrário do padrão do OSM. Trocar a ordem não dá erro — dá um mapa de
 * outro lugar do planeta, que é pior.
 *
 * ⛔ **Trocar esta constante é a única mudança necessária** para sair daqui:
 * proxy nosso com cache, MapTiler, Mapbox, tile próprio. O resto do arquivo é
 * geometria e não sabe de quem é o mapa.
 */
const TILE = (zoom: number, x: number, y: number) =>
  "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map" +
  `/MapServer/tile/${zoom}/${y}/${x}`;

/** Crédito do provedor. Não é enfeite: é condição de uso do basemap. */
const CREDITO = "Powered by Esri";

/** Lado do tile, em pixels. É fixo no padrão de tiles da web, em qualquer provedor. */
const LADO = 256;

/**
 * Quanto de mundo cabe na tela.
 *
 * A miniatura mostra o quarteirão e a via em que o veículo está — é o que
 * responde "onde ele parou". O mapa grande aproxima um passo, porque ali o
 * operador está conferindo o pátio, o posto, a alça de acesso.
 */
const ZOOM_MINIATURA = 16;
const ZOOM_GRANDE = 17;

/**
 * Coordenada geográfica para pixel absoluto do mundo, no zoom dado.
 *
 * É a projeção Web Mercator, a mesma que define a numeração dos tiles. Sem
 * ela não há como saber *qual* tile pedir nem onde encostá-lo: a posição do
 * pino é o centro da moldura, e são os tiles que se deslocam em volta.
 */
function pixelDoMundo(latitude: number, longitude: number, zoom: number) {
  const lado = LADO * 2 ** zoom;
  const rad = (latitude * Math.PI) / 180;
  const proporcaoY = (1 - Math.log(Math.tan(rad) + 1 / Math.cos(rad)) / Math.PI) / 2;
  return { x: ((longitude + 180) / 360) * lado, y: proporcaoY * lado };
}

/** Sem coordenada não há mapa — e não há ponto inventado no lugar dela. */
export function MiniMapa({
  latitude,
  longitude,
  endereco,
  placa,
}: {
  latitude: number | null;
  longitude: number | null;
  endereco: string | null;
  placa: string;
}) {
  const [aberto, setAberto] = useState(false);

  if (latitude === null || longitude === null) return null;

  const coordenadas = `${latitude.toFixed(5)}, ${longitude.toFixed(5)}`;
  const noGoogle = `https://www.google.com/maps?q=${latitude},${longitude}`;

  return (
    <>
      <button
        className="mapa-mini"
        type="button"
        onClick={() => setAberto(true)}
        title="Abrir o mapa maior"
      >
        <Cartografia latitude={latitude} longitude={longitude} zoom={ZOOM_MINIATURA} />
        <span className="mapa-rodape">
          <span className="mapa-endereco">{endereco ?? "posição registrada"}</span>
          <span className="mapa-coord">{coordenadas}</span>
        </span>
      </button>

      {aberto && (
        <ModalMapa
          aoFechar={() => setAberto(false)}
          latitude={latitude}
          longitude={longitude}
          endereco={endereco}
          placa={placa}
          coordenadas={coordenadas}
          noGoogle={noGoogle}
        />
      )}
    </>
  );
}

function ModalMapa({
  aoFechar,
  latitude,
  longitude,
  endereco,
  placa,
  coordenadas,
  noGoogle,
}: {
  aoFechar: () => void;
  latitude: number;
  longitude: number;
  endereco: string | null;
  placa: string;
  coordenadas: string;
  noGoogle: string;
}) {
  // Esc fecha. Num plantão, a mão está no teclado — obrigar a mirar num X é
  // atrito onde não deveria haver nenhum.
  useEffect(() => {
    const aoTeclar = (ev: KeyboardEvent) => {
      if (ev.key === "Escape") aoFechar();
    };
    window.addEventListener("keydown", aoTeclar);
    return () => window.removeEventListener("keydown", aoTeclar);
  }, [aoFechar]);

  return (
    <div className="mapa-fundo" role="dialog" aria-modal="true" onClick={aoFechar}>
      <div className="mapa-caixa" onClick={(ev) => ev.stopPropagation()}>
        <div className="mapa-cab">
          <div>
            <div className="mapa-titulo">
              <span className="placa">{placa}</span>
            </div>
            <div className="mapa-sub">{endereco ?? "posição registrada"}</div>
          </div>
          <button className="mapa-fechar" type="button" onClick={aoFechar} aria-label="Fechar">
            ✕
          </button>
        </div>

        <div className="mapa-grande">
          <Cartografia latitude={latitude} longitude={longitude} zoom={ZOOM_GRANDE} />
        </div>

        <div className="mapa-pe">
          <span className="mapa-coord">{coordenadas}</span>
          <a
            className="btn btn-primario"
            href={noGoogle}
            target="_blank"
            rel="noreferrer noopener"
          >
            Abrir no Google Maps
          </a>
        </div>
      </div>
    </div>
  );
}

/**
 * O mapa: os tiles que cobrem a moldura, com a coordenada no centro dela.
 *
 * Mede a moldura em vez de assumir tamanho, porque a miniatura e o mapa
 * grande têm larguras diferentes e as duas mudam com a janela. Do tamanho sai
 * a conta de quantos tiles pedir — nunca mais do que os que a tela mostra.
 */
function Cartografia({
  latitude,
  longitude,
  zoom,
}: {
  latitude: number;
  longitude: number;
  zoom: number;
}) {
  const moldura = useRef<HTMLDivElement>(null);
  const [caixa, setCaixa] = useState<{ largura: number; altura: number } | null>(null);
  // Quais tiles não chegaram. Um conjunto, e não um `falhou` só de sim/não:
  // um tile que engasga deixa um buraco, e buraco é honesto — o resto do mapa
  // continua verdadeiro. Só quando NENHUM chega é que o mapa não existe.
  const [falhas, setFalhas] = useState<ReadonlySet<string>>(new Set());

  useEffect(() => {
    const alvo = moldura.current;
    if (alvo === null) return;
    const observador = new ResizeObserver((entradas) => {
      const r = entradas[0].contentRect;
      setCaixa({ largura: r.width, altura: r.height });
    });
    observador.observe(alvo);
    return () => observador.disconnect();
  }, []);

  // Coordenada ou zoom novo é malha nova: as falhas da anterior não valem
  // mais, e mantê-las esconderia tiles que nunca foram pedidos.
  useEffect(() => setFalhas(new Set()), [latitude, longitude, zoom]);

  const tiles = useMemo(() => {
    if (caixa === null || caixa.largura === 0) return [];
    const centro = pixelDoMundo(latitude, longitude, zoom);
    // Canto superior esquerdo da moldura, em pixel do mundo. Todo o resto é
    // subtração a partir daqui.
    const esquerda = centro.x - caixa.largura / 2;
    const topo = centro.y - caixa.altura / 2;
    const quantos = 2 ** zoom;

    const lista: { chave: string; x: number; y: number; esq: number; top: number }[] = [];
    const ultimaColuna = Math.floor((esquerda + caixa.largura) / LADO);
    const ultimaLinha = Math.floor((topo + caixa.altura) / LADO);
    for (let tx = Math.floor(esquerda / LADO); tx <= ultimaColuna; tx++) {
      for (let ty = Math.floor(topo / LADO); ty <= ultimaLinha; ty++) {
        // Acima do polo não existe tile e pedir daria 404 — que aqui derrubaria
        // o mapa inteiro pelo `onError`. Na horizontal o mundo dá a volta,
        // então o índice da coluna é circular.
        if (ty < 0 || ty >= quantos) continue;
        const x = ((tx % quantos) + quantos) % quantos;
        lista.push({
          chave: `${tx}:${ty}`,
          x,
          y: ty,
          esq: tx * LADO - esquerda,
          top: ty * LADO - topo,
        });
      }
    }
    return lista;
  }, [latitude, longitude, zoom, caixa]);

  const semMapa = tiles.length > 0 && falhas.size >= tiles.length;

  return (
    <div className="mapa-tela" ref={moldura}>
      {tiles
        .filter((t) => !falhas.has(t.chave))
        .map((t) => (
          <img
            key={t.chave}
            className="mapa-tile"
            src={TILE(zoom, t.x, t.y)}
            alt=""
            width={LADO}
            height={LADO}
            decoding="async"
            style={{ left: `${t.esq}px`, top: `${t.top}px` }}
            onError={() =>
              setFalhas((antes) => new Set(antes).add(t.chave))
            }
          />
        ))}

      {/* ⛔ Sem internet, ou com o provedor fora do ar, fica o fundo neutro e o
          pino. Não volta o traçado desenhado que existia aqui antes: um mapa
          plausível e falso faz o operador concluir que o caminhão está numa via
          que não existe ali, e o risco é maior justamente quando a rede falha e
          ninguém percebe a troca. */}
      <span className="mapa-selo">{semMapa ? "mapa fora do ar" : CREDITO}</span>

      {/* O pino é o dado real: a coordenada que a IA usou para decidir. Fica no
          centro geométrico, e é o mapa que se move para encaixar embaixo. */}
      <svg className="mapa-pino" viewBox="-20 -20 40 40" aria-hidden="true">
        <circle r="13" className="m-halo" />
        <path
          d="M0 4 C -7 -3, -9 -9, -5.5 -13 C -2 -17, 2 -17, 5.5 -13 C 9 -9, 7 -3, 0 4 Z"
          className="m-pino"
          transform="translate(0 -3)"
        />
        <circle cy="-11" r="2.6" className="m-pino-furo" />
      </svg>
    </div>
  );
}
