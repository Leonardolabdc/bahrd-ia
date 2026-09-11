import { useEffect, useState } from "react";
import { api } from "../api";
import { CANAL_ROTULO, type Ocorrencia as TOcorrencia } from "../tipos";
import { Conversa } from "./Conversa";
import { Chevron, SetaVoltar } from "./Icones";
import { MiniMapa } from "./MiniMapa";

/**
 * Tela 2 — a ocorrência que a IA passou para o operador.
 *
 * Princípio 11: uma decisão por tela. O bloco de decisão fica aberto; contexto
 * e transcrição existem, mas **fechados por padrão** — o operador só abre o que
 * muda o que ele vai fazer em seguida.
 *
 * ⚠️ A trilha de auditoria era o terceiro retrátil e saiu da tela em
 * 03/09/2026, a pedido da operação. O dado continua no contrato da API.
 */
export function Ocorrencia({ id, aoVoltar }: { id: string; aoVoltar: () => void }) {
  const [oc, setOc] = useState<TOcorrencia | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    api
      .ocorrencia(id)
      .then(setOc)
      .catch((e: Error) => setErro(e.message));
  }, [id]);

  if (erro) return <p className="erro-api">Não foi possível carregar a ocorrência.<code>{erro}</code></p>;
  if (!oc) return <p className="carregando">Carregando…</p>;

  return (
    <main className="quadro">
      <button className="voltar" type="button" onClick={aoVoltar}>
        <SetaVoltar />
        Voltar
      </button>

      <div className="oc-cab">
        <h1>{oc.tipo_evento}</h1>
        <p className="oc-sub">
          <span className="placa">{oc.placa}</span> · {oc.interlocutor} ·{" "}
          {CANAL_ROTULO[oc.canal]} · {oc.aberta_ha}
        </p>
        <MiniMapa
          latitude={oc.latitude}
          longitude={oc.longitude}
          endereco={oc.endereco}
          placa={oc.placa}
        />
      </div>

      <section className="decisao" style={{ "--faixa": `var(--${oc.grau})` } as React.CSSProperties}>
        <div className="label">O que a IA apurou</div>
        {/* O briefing é gerado por prompt com saída estruturada e destaca o termo
            decisivo. Vem do nosso back-end, não do interlocutor. */}
        <p dangerouslySetInnerHTML={{ __html: oc.briefing }} />

        {/* O que a IA já fez, aberto por padrão. Quem recebe um caso crítico
            precisa saber em cinco segundos o que não precisa refazer. Desde que
            a trilha de auditoria saiu da tela, este é o único resumo do que
            aconteceu que o operador enxerga sem sair daqui. */}
        {oc.handoff.length > 0 && (
          <div className="handoff">
            <div className="handoff-cab">
              <span className="label">O que a IA já fez</span>
              {oc.probabilidade_real !== null && (
                <span
                  className={`prob${oc.probabilidade_real >= 90 ? " prob-alta" : ""}`}
                  title="Chance de ser real, estimada pela triagem antes de qualquer contato"
                >
                  {oc.probabilidade_real}% de chance de ser real
                </span>
              )}
            </div>
            <ul>
              {/* ⚠️ **Renderiza HTML, como o briefing logo acima.**
                  Até 03/09/2026 saía como texto puro, e as tags apareciam
                  cruas na tela: "O cliente &lt;b&gt;pediu atendimento
                  humano&lt;/b&gt;".

                  ⛔ Só é seguro porque **todo handoff nasce no nosso
                  back-end**, nunca do modelo nem do interlocutor. A única
                  interpolação de terceiro é o motivo de falha de entrega, que
                  vem do webhook da Meta e passa por `html.escape` na origem.
                  Quem acrescentar um handoff novo com texto de fora tem de
                  escapar lá, não aqui. */}
              {oc.handoff.map((passo, i) => (
                <li key={i} dangerouslySetInnerHTML={{ __html: passo }} />
              ))}
            </ul>
          </div>
        )}

        {/* ⚠️ Lista vazia não vira bloco vazio. Os casos encerrados ficaram sem
            ação nenhuma em 03/09/2026 (os três botões de lá não faziam nada), e
            sem esta guarda sobraria o espaçamento de uma barra de botões que
            não existe mais. */}
        {oc.acoes.length > 0 && (
          <div className="acoes">
            {oc.acoes.map((acao, i) => (
              <button key={acao} className={`btn${i === 0 ? " btn-primario" : ""}`} type="button">
                {acao}
              </button>
            ))}
          </div>
        )}
      </section>

      <div className="detalhes">
        {/* Sem conversa quer dizer que a triagem passou o caso adiante antes de
            qualquer contato — não que a IA ficou parada. O que ela fez está no
            bloco acima; aqui só se diz por que não há diálogo. */}
        {oc.conversa.length > 0 ? (
          <details>
            <summary>
              <Chevron />
              {oc.canal === "LIGACAO" ? "Ver a transcrição da ligação" : "Ver a conversa no WhatsApp"}
              <span className="cont">
                {oc.turnos} {oc.canal === "LIGACAO" ? "turnos" : "mensagens"} · {oc.duracao}
              </span>
            </summary>
            <div className="painel-det">
              <Conversa
                canal={oc.canal}
                turnos={oc.conversa}
                nome={oc.interlocutor.split(",")[0]}
                telefone={oc.telefone}
              />
            </div>
          </details>
        ) : (
          <p className="sem-conversa">
            Sem conversa — o contato deste caso é seu. A IA parou na triagem e
            entregou o que apurou.
          </p>
        )}

        <details>
          <summary>
            <Chevron />
            Ficha do atendimento
          </summary>
          <div className="painel-det">
            <dl className="dl">
              {Object.entries(oc.ficha).map(([rotulo, valor]) => (
                <div key={rotulo} style={{ display: "contents" }}>
                  <dt>{rotulo}</dt>
                  <dd>{valor}</dd>
                </div>
              ))}
            </dl>
          </div>
        </details>

        {/* ⚠️ **A trilha de auditoria saiu da tela em 03/09/2026**, a pedido do
            A operação. Era um `<details>` retrátil com "política vX · prompt vY"
            no contador.

            ⛔ Saiu **só da tela**. O dado continua inteiro: `auditoria`,
            `politica_versao` e `prompt_versao` seguem no contrato de
            `/painel/ocorrencias/{id}`, e `sessao.anotar` continua registrando
            cada passo. Quem precisar do rastro tem a API e o Langfuse, que
            desde hoje recebe também a origem e a triagem.

            Voltar é remontar este bloco. Nada foi apagado. */}
      </div>
    </main>
  );
}
