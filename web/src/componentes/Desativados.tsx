import { useEffect, useState } from "react";
import { api } from "../api";
import type { Desativado } from "../tipos";
import { Info } from "./Icones";

/**
 * Veículos com alarme suprimido por um período.
 *
 * **Por que é uma aba separada de "Encerrados".** Vem dos scripts reais da
 * Central (doc 23): quando o cliente confirma manutenção ou transporte, o
 * operador não encerra o assunto — ele diz *"iremos desconsiderar os eventos
 * enquanto no local"*.
 *
 * São coisas diferentes. Encerrado quer dizer **acabou**; desativado quer dizer
 * **continua acontecendo, e é esperado**. Misturar os dois faz o operador achar
 * que o caso está resolvido enquanto o caminhão ainda está na prancha — e faz o
 * mesmo veículo disparar de novo em minutos.
 */
const DESFECHO_EM_PORTUGUES: Record<string, string> = {
  reboque_autorizado: "Reboque autorizado",
  transporte_em_prancha_ou_balsa: "Transporte em prancha ou balsa",
  veiculo_em_manutencao: "Veículo em manutenção",
  local_e_base_do_cliente: "Na base do cliente",
};

export function Desativados({ aoAbrir }: { aoAbrir: (id: string) => void }) {
  const [itens, setItens] = useState<Desativado[] | null>(null);

  useEffect(() => {
    const buscar = () => api.desativados().then(setItens).catch(() => setItens([]));
    buscar();
    // O prazo vira "expirado" com o relógio, não com uma ação de alguém — sem
    // recarregar, a tela mentiria sobre o que ainda está suprimido.
    const t = setInterval(buscar, 15_000);
    return () => clearInterval(t);
  }, []);

  if (itens === null) return <main className="quadro" role="tabpanel" />;

  if (itens.length === 0) {
    return (
      <main className="quadro painel-cheio" role="tabpanel">
        <p className="chamada">
          Nenhum veículo com alarme suprimido agora.
        </p>
        <p className="vazio-explica">
          <Info /> Entram aqui os casos que o cliente confirmou como manutenção
          ou transporte. A Central não encerra esses — ela desconsidera os
          eventos enquanto a situação durar.
        </p>
      </main>
    );
  }

  const expirados = itens.filter((i) => i.expirado).length;

  return (
    <main className="quadro painel-cheio" role="tabpanel">
      <p className="chamada">
        {itens.length} veículo{itens.length > 1 ? "s" : ""} com alarme suprimido
        {expirados > 0 && (
          <> · <b className="alerta">{expirados} com prazo vencido</b></>
        )}
      </p>

      {/* ⚠️ **Cartão clicável desde 03/09/2026.** Era um `<article>` inerte:
          a aba mostrava placa, evento e prazo, e parava ali. Quem quisesse ver
          por que aquele veículo foi suprimido, ou o que o cliente disse, não
          tinha para onde ir — nas outras três abas o cartão abre a ocorrência
          inteira, e não havia motivo para esta ser a exceção.

          `<button>` e não `<div onClick>`: entra na navegação por teclado e o
          leitor de tela anuncia como ação, igual ao de "Encerrados". */}
      <div className="grade-fila">
        {itens.map((i) => (
          <button
            key={i.ocorrencia_id}
            className={`cartao ${i.expirado ? "grau-alta" : "grau-baixa"}`}
            type="button"
            title={`Ver a conversa que levou à supressão do ${i.placa}`}
            onClick={() => aoAbrir(i.ocorrencia_id)}
          >
            <span className="cartao-topo">
              <span className="cartao-tipo">{i.tipo_evento}</span>
              <span className="cartao-hora">{i.desativado_em}</span>
            </span>

            <span className="cartao-quem">
              <span className="placa">{i.placa}</span>
              <span className="cartao-pessoa">{i.interlocutor}</span>
            </span>

            <span className="cartao-desfecho">
              {DESFECHO_EM_PORTUGUES[i.desfecho] ?? i.desfecho.replace(/_/g, " ")}
            </span>

            <span className="cartao-rodape">
              {/* O prazo é a informação que esta aba existe para dar: é o que
                  distingue "suprimido" de "encerrado". Fica por último e em
                  destaque quando vence. */}
              <span className={i.expirado ? "alerta" : ""}>
                {i.expirado ? "prazo vencido" : `até ${i.ate}`}
              </span>
            </span>
          </button>
        ))}
      </div>

      {expirados > 0 && (
        <p className="vazio-explica">
          <Info /> Prazo vencido quer dizer que o período combinado passou e
          ninguém confirmou que a situação continua. Pelo script da Central, o
          cliente deveria ter avisado — vale conferir.
        </p>
      )}
    </main>
  );
}
