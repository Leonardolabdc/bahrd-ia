import { useEffect, useState } from "react";
import { mmss } from "../formato";
import { CANAL_ROTULO, type ItemFila } from "../tipos";
import { Conversa } from "./Conversa";
import { SetaVoltar } from "./Icones";
import { MiniMapa } from "./MiniMapa";

/**
 * Tela 3 — acompanhar um atendimento em andamento sem interromper.
 *
 * A transcrição avança turno a turno. No Sprint 2 isso vem por WebSocket do
 * orquestrador; o formato de `falas` e `roteiro` já é o final, então só a
 * origem muda.
 */
export function AoVivo({ item, aoVoltar }: { item: ItemFila | null; aoVoltar: () => void }) {
  const [passo, setPasso] = useState(0);
  const [ateFala, setAteFala] = useState(0);
  const [decorrido, setDecorrido] = useState(item?.decorrido_s ?? 0);

  const roteiro = item?.roteiro ?? [];
  const todasAsFalas = item?.falas ?? [];
  // Conversa real: as mensagens JÁ foram trocadas. Revelar aos poucos aqui
  // faria o operador achar que a IA travou enquanto ela já respondeu três vezes.
  const revelaAosPoucos = !item?.ao_vivo_real;

  useEffect(() => {
    const id = setInterval(() => setDecorrido((s) => s + 1), 1000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    if (roteiro.length < 2) return;
    const id = setTimeout(
      () => setPasso((p) => (p + 1) % roteiro.length),
      roteiro[passo].duracao_s * 1000,
    );
    return () => clearTimeout(id);
  }, [roteiro, passo]);

  useEffect(() => {
    if (!revelaAosPoucos || ateFala >= todasAsFalas.length) return;
    const id = setTimeout(() => setAteFala((n) => n + 1), ateFala === 0 ? 600 : 3200);
    return () => clearTimeout(id);
  }, [revelaAosPoucos, todasAsFalas.length, ateFala]);

  // A ocorrência pode sair da fila enquanto a tela está aberta — foi o que
  // acontece quando a IA encerra. Dizer isso é melhor que sumir com a tela.
  if (item === null) {
    return (
      <main className="quadro">
        <button className="voltar" type="button" onClick={aoVoltar}>
          <SetaVoltar />
          Voltar
        </button>
        <p className="sem-conversa">
          Esta ocorrência saiu da fila — a IA encerrou ou passou para um operador.
          Ela está em <b>Encerrados</b>, com a conversa inteira.
        </p>
      </main>
    );
  }

  const falasVisiveis = revelaAosPoucos ? todasAsFalas.slice(0, ateFala) : todasAsFalas;
  const atual = roteiro[passo];
  const faltamFalas = revelaAosPoucos && ateFala < todasAsFalas.length;

  return (
    <main className="quadro">
      <button className="voltar" type="button" onClick={aoVoltar}>
        <SetaVoltar />
        Voltar
      </button>

      <div className="oc-cab">
        <h1>{item.tipo_evento}</h1>
        <p className="oc-sub">
          <span className="placa">{item.placa}</span> · {item.interlocutor} ·{" "}
          {CANAL_ROTULO[item.canal]}
        </p>
        <MiniMapa
          latitude={item.latitude}
          longitude={item.longitude}
          endereco={item.endereco}
          placa={item.placa}
        />
      </div>

      <div className={`vivo-status ${atual?.falando ? "falando" : ""}`}>
        <span className="vivo" />
        <span>{atual?.frase ?? "Em atendimento"}</span>
        <span className="decorrido">{mmss(decorrido)}</span>
      </div>

      <div className="transcricao">
        {/* Sem falas ainda: a IA está no primeiro contato e ninguém respondeu.
            Dizer isso é informação — deixar a área em branco parece defeito. */}
        {falasVisiveis.length === 0 ? (
          <p className="sem-conversa">
            Ninguém falou ainda. A IA está no primeiro contato.
          </p>
        ) : (
          <Conversa
            canal={item.canal}
            turnos={falasVisiveis}
            nome={item.interlocutor.split(",")[0]}
          />
        )}
        {faltamFalas && (
          <div className="digitando" aria-label="aguardando a próxima mensagem">
            <i />
            <i />
            <i />
          </div>
        )}
      </div>

      {/* ⛔ **A barra de ações saiu em 03/09/2026, a pedido da operação.**
          Tinha "Assumir agora" e "Deixar a IA continuar".

          "Assumir agora" não tinha `onClick`: aceitava o clique e não fazia
          nada. Num caso ao vivo isso é o pior tipo de mentira que uma tela pode
          contar — quem apertasse sairia achando que tinha assumido a conversa,
          e a IA continuaria falando com o cliente sozinha.

          "Deixar a IA continuar" funcionava, mas só chamava `aoVoltar`. O nome
          prometia uma decisão e entregava um "fechar": deixar a IA continuar é
          o que acontece de qualquer jeito quando ninguém faz nada.

          Sair da tela continua pelo «Voltar» do topo, que é o que os dois
          botões de fato faziam. Voltam quando existir o comando por trás. */}
    </main>
  );
}
