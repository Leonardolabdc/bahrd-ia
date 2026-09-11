import { useEffect, useRef, useState } from "react";
import { CANAL_ROTULO, GRAU_ROTULO, type ItemFila } from "../tipos";
import { Seta } from "./Icones";

/**
 * A narração do que a IA está fazendo vem do **estado da máquina**, nunca do
 * modelo: estado da ocorrência + passo do playbook + ferramenta em execução.
 * Se o LLM escrevesse estas frases, o painel poderia mentir sobre o que a IA fez.
 *
 * O avanço dos passos aqui simula o que, no Sprint 2, chega por WebSocket
 * vindo do orquestrador. O componente já lê `roteiro` no formato final.
 */
function usePasso(item: ItemFila): number {
  const [passo, setPasso] = useState(0);

  useEffect(() => {
    if (item.roteiro.length < 2) return;
    const duracao = item.roteiro[passo].duracao_s * 1000;
    const id = setTimeout(() => setPasso((p) => (p + 1) % item.roteiro.length), duracao);
    return () => clearTimeout(id);
  }, [item, passo]);

  return passo;
}

/** Chacoalha o cartão para dizer "não há tela aqui ainda" sem abrir um alerta. */
function useChacoalha() {
  const ref = useRef<HTMLButtonElement>(null);
  const chacoalha = () =>
    ref.current?.animate(
      [
        { transform: "translateX(0)" },
        { transform: "translateX(-3px)" },
        { transform: "translateX(3px)" },
        { transform: "translateX(0)" },
      ],
      { duration: 200 },
    );
  return { ref, chacoalha };
}

/**
 * Cartão da grade — a mesma anatomia nas três abas.
 *
 * Quatro faixas fixas, sempre na mesma ordem e no mesmo lugar:
 *
 *     faixa de cor · tipo do evento · grau
 *     placa · quem
 *     uma linha de destaque (nota, status ou desfecho)
 *     hora · data · canal
 *
 * A repetição é o ponto. Numa lista, o olho lê da esquerda para a direita e
 * desce; numa grade, ele salta. Se cada aba desenhasse o cartão à sua maneira,
 * cada salto exigiria reaprender onde está a informação — e a grade ficaria
 * mais lenta de ler que a lista que ela substituiu.
 */
export function Cartao({
  item,
  destaque,
  rodape,
  aoAbrir,
  abrivel,
}: {
  item: ItemFila;
  destaque?: React.ReactNode;
  rodape?: React.ReactNode;
  aoAbrir: () => void;
  abrivel: boolean;
}) {
  const { ref, chacoalha } = useChacoalha();

  return (
    <button
      ref={ref}
      type="button"
      className={`cartao${abrivel ? "" : " cartao-inerte"}`}
      style={{ "--faixa": `var(--${item.grau})` } as React.CSSProperties}
      onClick={() => (abrivel ? aoAbrir() : chacoalha())}
      title={item.momento_completo ?? undefined}
    >
      <span className="cartao-topo">
        <span className="cartao-tipo">{item.tipo_evento}</span>
        {/* ⛔ Antes do grau, colado no tipo do evento. Quem lê a fila às três da
            manhã lê "Pânico" e reage — o selo tem de estar no caminho dessa
            leitura, não perdido no fim da linha. */}
        {item.origem === "teste" && (
          <span className="selo-teste" title="Disparado pela tela de eventos de teste da Central. Não veio do sistema da Bahrd.">
            teste
          </span>
        )}
        <span className="grau">{GRAU_ROTULO[item.grau]}</span>
      </span>

      <span className="cartao-quem">
        <span className="placa">{item.placa}</span>
        <span className="cartao-pessoa">{item.interlocutor}</span>
      </span>

      {destaque}

      <span className="cartao-pe">
        {rodape ?? <span className="canal-tag">{CANAL_ROTULO[item.canal]}</span>}
        <span className="cartao-quando">
          {item.momento}
          {item.dia && <i>{item.dia}</i>}
        </span>
        <Seta />
      </span>
    </button>
  );
}

export function LinhaPrecisaDeVoce({ item, aoAbrir }: { item: ItemFila; aoAbrir: () => void }) {
  // A leitura de contexto é um parágrafo. No cartão ela entra cortada em duas
  // linhas: quem precisa do texto inteiro abre a ocorrência, e quem está
  // varrendo a grade precisa é enxergar que ela existe.
  const destaque = item.nota ? (
    <span className="cartao-nota">{item.nota}</span>
  ) : item.leitura_ia ? (
    <span className="cartao-nota cartao-nota-longa">{item.leitura_ia}</span>
  ) : null;

  return (
    <Cartao
      item={item}
      destaque={destaque}
      aoAbrir={aoAbrir}
      abrivel={item.tem_detalhe}
    />
  );
}

export function LinhaIaFazendo({ item, aoAbrir }: { item: ItemFila; aoAbrir: () => void }) {
  const passo = usePasso(item);
  const atual = item.roteiro[passo];

  const destaque = atual ? (
    <span className={`cartao-status ${atual.falando ? "falando" : "status-espera"}`}>
      <span className="vivo" />
      <span className="status-txt">{atual.frase}</span>
    </span>
  ) : null;

  return (
    <Cartao item={item} destaque={destaque} aoAbrir={aoAbrir} abrivel={item.tem_ao_vivo} />
  );
}
