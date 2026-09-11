import type { Canal, Turno } from "../tipos";

/**
 * Toda conversa usa o mesmo chat, em qualquer canal.
 *
 * A réplica do WhatsApp existe porque o operador reconhece a tela em meio
 * segundo e não precisa decifrar quem falou o quê. Ligação também vem assim:
 * é o mesmo diálogo, e alternar entre dois formatos custava mais atenção do
 * que ganhava em precisão.
 *
 * O que **não** é replicado numa ligação: o ✓✓. Confirmação de leitura é um
 * fato do WhatsApp — ligação não tem. Desenhar um ali seria inventar uma
 * prova de entrega que não existe. O cabeçalho diz qual dos dois é.
 */
export function Conversa({
  canal,
  turnos,
  nome,
  telefone,
}: {
  canal: Canal;
  turnos: Turno[];
  nome?: string;
  telefone?: string | null;
}) {
  return (
    <ConversaWhatsApp
      turnos={turnos}
      nome={nome}
      telefone={telefone}
      ligacao={canal === "LIGACAO"}
    />
  );
}

/* ─────────────────────────────── ícones ─────────────────────────────── */

const CheckDuplo = ({ lido }: { lido: boolean }) => (
  <svg
    width="16"
    height="11"
    viewBox="0 0 16 11"
    aria-label={lido ? "lido" : "entregue"}
    className={lido ? "zap-lido" : undefined}
  >
    <path
      d="M1.5 5.9 4 8.4 9.1 2.4"
      stroke="currentColor"
      strokeWidth="1.3"
      fill="none"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
    <path
      d="M6.6 5.9 9.1 8.4 14.2 2.4"
      stroke="currentColor"
      strokeWidth="1.3"
      fill="none"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

const Play = () => (
  <svg width="13" height="14" viewBox="0 0 13 14" aria-hidden="true">
    <path d="M1.5 1l10 6-10 6z" fill="currentColor" />
  </svg>
);

const Microfone = () => (
  <svg width="12" height="16" viewBox="0 0 12 16" aria-hidden="true" className="zap-mic">
    <rect x="4" y="1" width="4" height="8" rx="2" fill="currentColor" />
    <path d="M2 7a4 4 0 0 0 8 0M6 11v3" stroke="currentColor" strokeWidth="1.2" fill="none" strokeLinecap="round" />
  </svg>
);

const Pessoa = () => (
  <svg width="20" height="20" viewBox="0 0 20 20" aria-hidden="true">
    <circle cx="10" cy="6.5" r="3.6" fill="currentColor" />
    <path d="M2.6 18c0-4 3.3-6.2 7.4-6.2s7.4 2.2 7.4 6.2" fill="currentColor" />
  </svg>
);

const Fone = () => (
  <svg width="17" height="17" viewBox="0 0 20 20" aria-hidden="true">
    <path
      d="M6.3 2.6 8 6.1 6.3 7.8c-.5.5-.5 1 0 1.8a11 11 0 0 0 4.1 4.1c.8.5 1.3.5 1.8 0l1.7-1.7 3.5 1.7v2.6c0 .9-.7 1.6-1.6 1.5C7.9 17.2 2.8 12.1 2.2 4.2c-.1-.9.6-1.6 1.5-1.6h2.6z"
      fill="currentColor"
    />
  </svg>
);

/* ─────────────────────────────── auxiliares ─────────────────────────────── */

const mmssCurto = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;

/** Onda estática: representa a nota de voz sem prometer um player que ainda não
 *  existe. O áudio real vem do object storage no Sprint 3. */
function Onda({ semente }: { semente: number }) {
  return (
    <div className="zap-onda">
      {Array.from({ length: 28 }, (_, i) => (
        <i key={i} style={{ height: `${4 + ((Math.sin(semente + i * 1.7) + 1) / 2) * 14}px` }} />
      ))}
    </div>
  );
}

/** Horário e confirmação de entrega. Some inteiro quando não há nem um nem outro
 *  — conversa gerada pelo pipeline ainda não carrega horário, e um espaço
 *  reservado vazio deforma a bolha. */
function Meta({ t, ticks }: { t: Turno; ticks: boolean }) {
  const mostraTicks = ticks && t.quem === "ia" && !!t.status && t.status !== "enviado";
  if (!t.horario && !mostraTicks) return null;
  return (
    <span className="zap-meta">
      {t.horario}
      {mostraTicks && <CheckDuplo lido={t.status === "lido"} />}
    </span>
  );
}

/** Marca o trecho que o STT não entendeu, para o operador não ler como fato. */
function TextoTranscrito({ fala }: { fala: string }) {
  return (
    <>
      {fala.split(/(\[trecho não compreendido\])/g).map((p, i) =>
        p === "[trecho não compreendido]" ? (
          <span className="zap-duvida" key={i} title="A transcrição não entendeu este trecho">
            {p}
          </span>
        ) : (
          <span key={i}>{p}</span>
        ),
      )}
    </>
  );
}

/* ─────────────────────────────── o chat ─────────────────────────────── */

function ConversaWhatsApp({
  turnos,
  nome,
  telefone,
  ligacao = false,
}: {
  turnos: Turno[];
  nome?: string;
  telefone?: string | null;
  ligacao?: boolean;
}) {
  return (
    <div className={`zap${ligacao ? " zap-ligacao" : ""}`}>
      <div className="zap-cabecalho">
        <span className="zap-avatar">{ligacao ? <Fone /> : <Pessoa />}</span>
        <div>
          <div className="zap-nome">{nome ?? "Cliente"}</div>
          <div className="zap-numero">
            {ligacao ? `Ligação · transcrição${telefone ? ` · ${telefone}` : ""}` : telefone}
          </div>
        </div>
      </div>

      <div className="zap-corpo">
        <span className="zap-dia">{ligacao ? "transcrição da ligação" : "hoje"}</span>

        {turnos.map((t, i) => {
          const daIA = t.quem === "ia";
          // Só a primeira bolha de cada sequência do mesmo autor leva rabinho,
          // como no WhatsApp.
          const primeira = i === 0 || turnos[i - 1].quem !== t.quem;

          return (
            <div key={i} style={{ display: "contents" }}>
              {t.tipo === "template" && (
                <span
                  className="zap-template"
                  title="Passadas 24 h da última resposta do cliente, o WhatsApp só deixa
                         iniciar conversa com uma mensagem pré-aprovada por eles."
                >
                  mensagem pré-aprovada pelo WhatsApp
                </span>
              )}

              <div
                className={`zap-msg ${daIA ? "zap-ia" : "zap-cliente"} ${primeira ? "zap-primeira" : ""}`}
              >
                {t.tipo === "audio" ? (
                  <>
                    <div className="zap-audio">
                      <span className="zap-play">
                        <Play />
                      </span>
                      <Onda semente={i} />
                      <Microfone />
                    </div>
                    <span className="zap-dur">{mmssCurto(t.duracao_s ?? 0)}</span>

                    <div className="zap-transcrito">
                      <span className="zap-selo">
                        {t.transcrito ? "transcrição automática" : "o que a IA falou"}
                      </span>
                      {t.transcrito ? <TextoTranscrito fala={t.fala} /> : t.fala}
                      <Meta t={t} ticks={!ligacao} />
                    </div>
                  </>
                ) : (
                  <>
                    <Meta t={t} ticks={!ligacao} />
                    {t.fala}
                  </>
                )}

                {t.botoes.length > 0 && (
                  <div className="zap-botoes">
                    {t.botoes.map((b) => {
                      // Marca qual botão o cliente tocou: a mensagem seguinte
                      // dele com texto idêntico ao rótulo veio de um toque.
                      const escolhido =
                        turnos[i + 1]?.quem === "cliente" && turnos[i + 1].fala === b;
                      return (
                        <span
                          className={`zap-botao ${escolhido ? "zap-escolhido" : ""}`}
                          key={b}
                          title={escolhido ? "O cliente tocou neste botão" : undefined}
                        >
                          {b}
                        </span>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
