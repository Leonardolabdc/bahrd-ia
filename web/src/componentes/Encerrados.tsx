import { useEffect, useState } from "react";
import { api } from "../api";
import { CANAL_ROTULO, type Encerrados as Dados } from "../tipos";
import { Chevron, Confere, Info } from "./Icones";

/**
 * O desfecho em português de gente.
 *
 * O código (`sem_causa_real_equipamento_para_inspecao`) é o identificador da
 * lista branca e precisa continuar existindo tal e qual — é por ele que a
 * política valida o fechamento. Mas trocar `_` por espaço não é traduzir:
 * saía "Sem causa real equipamento para inspecao", sem acento e sem sentido.
 * Aqui cada código tem a frase que um operador diria.
 *
 * Código novo que ainda não tenha frase cai no formato antigo em vez de sumir.
 */
const DESFECHO_EM_PORTUGUES: Record<string, string> = {
  chave_geral_desligada_pelo_motorista: "Motorista desligou a chave geral",
  veiculo_em_manutencao: "Veículo em manutenção",
  falha_de_instalacao_reportada: "Problema elétrico relatado",
  velocidade_normalizada_apos_contato: "Velocidade normalizou após o contato",
  terceira_ocorrencia_gestor_notificado: "3ª do dia · gestora avisada",
  justificado_pelo_motorista: "Motorista justificou",
  orientacao_registrada: "Orientação registrada",
  sem_resposta_orientacao_enviada: "Sem resposta · orientação enviada",
  sem_resposta_apos_tentativas: "Sem resposta após 3 tentativas",
  // Motivos que, com operador na mesa, virariam escalonamento. Nesta fase a IA
  // encerra e grava o motivo — o nome tem de deixar claro que não é "resolvido".
  sem_resposta_evento_critico: "Sem resposta em evento crítico",
  acima_do_limiar_de_risco: "Triagem acima do limiar de risco",
  escalado_pela_ia: "A IA pediu apoio humano",
  falha_tecnica_no_atendimento: "Falha técnica no atendimento",
  mensagem_nao_entregue: "Mensagem não chegou ao cliente",
  triagem_indisponivel: "Triagem indisponível",
  desfecho_recusado_fora_da_lista_branca: "Desfecho recusado pela política",
  reboque_sem_autorizacao_do_gestor: "Reboque sem autorização do gestor",
  reboque_nao_reconhecido: "Motorista não reconhece o reboque",
  causa_normal_nao_confirmada: "Causa normal não confirmada",
  resposta_inconclusiva: "Resposta inconclusiva",
  possivel_ocorrencia_real: "Possível ocorrência real",
  coacao: "Sinal de coação",
  problema_mecanico_reportado: "Problema mecânico relatado",
  reboque_autorizado: "Reboque autorizado pela gestora",
  transporte_em_prancha_ou_balsa: "Transporte em prancha ou balsa",
  falso_positivo_gps: "Falso positivo de GPS",
  acionamento_acidental_confirmado: "Botão acionado sem querer",
  alarme_falso_confirmado_por_triagem: "Alarme falso confirmado na triagem",
  sem_causa_real_equipamento_para_inspecao: "Sem causa real · rastreador para inspeção",
};

function legivel(desfecho: string) {
  const traduzido = DESFECHO_EM_PORTUGUES[desfecho];
  if (traduzido) return traduzido;
  const texto = desfecho.replace(/_/g, " ");
  return texto.charAt(0).toUpperCase() + texto.slice(1);
}

/**
 * Tela 5 — o que já foi resolvido, pela IA ou pelo operador.
 *
 * Existe por um motivo específico: sem ela o painel só mostra o que deu
 * trabalho. A contenção viraria um número no dashboard que ninguém consegue
 * conferir caso a caso — e o valor inteiro da POC depende de conseguir abrir
 * qualquer fechamento da IA e ver o que ela fez.
 */
export function Encerrados({ aoAbrir }: { aoAbrir: (id: string) => void }) {
  const [d, setD] = useState<Dados | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    api
      .encerrados()
      .then(setD)
      .catch((e: Error) => setErro(e.message));
  }, []);

  if (erro)
    return (
      <p className="erro-api">
        Não foi possível carregar os encerrados.<code>{erro}</code>
      </p>
    );
  if (!d) return <p className="carregando">Carregando…</p>;

  const total = d.total_ia + d.total_operador;
  const contencao = total ? Math.round((d.total_ia / total) * 100) : 0;

  return (
    <main className="quadro painel-cheio" role="tabpanel">
      <section className="encerrados-resumo">
        <div className="enc-num">
          <div className="label">Fechadas pela IA</div>
          <strong>{d.total_ia}</strong>
        </div>
        {/* ⚠️ Este número conta casos que **não estão na lista abaixo**, e o
            rótulo precisa dizer isso. A lista mostra só o que a IA fechou
            sozinha (mudança de 03/09/2026); o contador continua somando os dois
            porque a contenção é uma razão e sem denominador ela não existe. */}
        <div className="enc-num">
          <div className="label">Fechadas pelo operador</div>
          <strong>{d.total_operador}</strong>
          <div className="enc-nota">não listadas aqui</div>
        </div>
        <div className="enc-num enc-num-destaque">
          <div className="label">Contenção do turno</div>
          <strong>
            {contencao}
            <small>%</small>
          </strong>
        </div>
      </section>

      {/* Mesma anatomia de cartão das outras duas abas. O que muda é o
          conteúdo da faixa de destaque — aqui, quem fechou e com qual
          desfecho. */}
      <div className="grade-fila">
        {d.itens.map((e) => (
          <button
            key={e.ocorrencia_id}
            className={`cartao por-${e.encerrada_por}${e.tem_detalhe ? "" : " cartao-inerte"}`}
            type="button"
            disabled={!e.tem_detalhe}
            title={
              e.tem_detalhe
                ? `Ver como ${e.responsavel} tratou esta ocorrência`
                : "Linha de histórico — sem registro completo"
            }
            onClick={() => aoAbrir(e.ocorrencia_id)}
          >
            <span className="cartao-topo">
              <span className="cartao-tipo">{e.tipo_evento}</span>
              {/* Quem fechou, com nome quando é gente: quem responde por um
                  fechamento é uma pessoa localizável depois, não um papel. */}
              <span className="enc-por-papel">
                {e.encerrada_por === "ia" && <Confere />}
                {e.encerrada_por === "ia" ? "IA" : e.responsavel}
              </span>
            </span>

            <span className="cartao-quem">
              <span className="placa">{e.placa}</span>
              <span className="cartao-pessoa">{e.interlocutor}</span>
            </span>

            <span className="cartao-desfecho">{legivel(e.desfecho)}</span>

            <span className="cartao-pe">
              <span className="canal-tag">{CANAL_ROTULO[e.canal]}</span>
              <span className="cartao-quando">
                {e.encerrada_em}
                {e.encerrada_dia && <i>{e.encerrada_dia}</i>}
              </span>
              <Chevron />
            </span>
          </button>
        ))}
      </div>

      <p className="nota-papel nota-pe">
        <Info />
        Só o que a IA resolveu sozinha aparece nesta lista. Todo cartão abre a
        ocorrência inteira, com a conversa que aconteceu: um fechamento que não
        pode ser conferido não conta como contenção.
      </p>
    </main>
  );
}
