import { useEffect, useState } from "react";
import { api } from "../api";
import type { NumeroRemovido } from "../tipos";

/**
 * Números que pediram para sair dos avisos de um veículo.
 *
 * **Por que é uma aba, e não uma linha de relatório.** Uma linha de celular
 * cancelada é reciclada pela operadora, e o cadastro da Bahrd continua apontando
 * para ela: quem atende passa a receber alarme de um caminhão que nunca foi
 * seu. Parar de mandar depois do pedido é **obrigação de plataforma** — ignorar
 * derruba a nota de qualidade do número na Meta e, no limite, tira a conta do
 * ar, e aí nenhum cliente recebe nada.
 *
 * ⚠️ **Não confundir com «Desativação temporária».** Lá é o veículo com alarme
 * suprimido por um tempo, a pedido do dono, e volta sozinho. Aqui é o contato
 * que saiu: o alarme continua valendo, e o veículo segue disparando para quem
 * mais estiver no cadastro.
 *
 * ⛔ **O bloqueio é remendo nosso, não a correção.** Enquanto a Bahrd não trocar
 * o telefone no cadastro, todo evento novo daquele veículo continua tentando
 * este número. É o operador, lendo esta lista, quem pede a correção — por isso
 * a tela insiste nisso no rodapé, em vez de só listar.
 */
export function NumerosRemovidos() {
  const [itens, setItens] = useState<NumeroRemovido[] | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    api
      .numerosRemovidos()
      .then(setItens)
      .catch((e: Error) => setErro(e.message));
  }, []);

  if (erro !== null)
    return (
      <main className="quadro painel-cheio" role="tabpanel">
        <p className="vazio-explica">Não deu para ler a lista: {erro}</p>
      </main>
    );

  if (itens === null)
    return (
      <main className="quadro painel-cheio" role="tabpanel">
        <p className="vazio-explica">Carregando…</p>
      </main>
    );

  return (
    <main className="quadro painel-cheio" role="tabpanel">
      <p className="chamada">
        {itens.length === 0
          ? "Nenhum número removido"
          : `${itens.length} número${itens.length > 1 ? "s" : ""} fora dos avisos`}
      </p>

      {itens.length === 0 ? (
        <p className="vazio-explica">
          Quando alguém responder <b>REMOVER</b> à notificação e confirmar, o
          número aparece aqui e para de receber os avisos daquele veículo.
        </p>
      ) : (
        <div className="grade-fila">
          {itens.map((i) => (
            <article className="cartao grau-baixa" key={`${i.telefone}-${i.placa}`}>
              <span className="cartao-topo">
                <span className="cartao-tipo">{i.telefone}</span>
                <span className="cartao-hora">{i.quando}</span>
              </span>

              <span className="cartao-quem">
                <span className="placa">{i.placa}</span>
                <span className="cartao-pessoa">não recebe mais</span>
              </span>

              {/* A frase do cliente fica visível: é ela que deixa o operador
                  julgar se foi pedido de verdade ou engano da leitura da IA —
                  e é o que ele leva para a Bahrd ao pedir a correção. */}
              {i.pedido && <span className="cartao-desfecho">“{i.pedido}”</span>}

              <span className="cartao-rodape">{i.ocorrencia_id}</span>
            </article>
          ))}
        </div>
      )}

      <p className="rodape-lista">
        Estes números não recebem mais os avisos <b>da placa ao lado, e só
        dela</b>. O alarme continua valendo para quem mais estiver no cadastro.
        A correção de verdade é a <b>Bahrd atualizar o telefone</b> do veículo:
        enquanto não atualizar, todo evento novo tenta este contato e é barrado
        aqui.
      </p>
    </main>
  );
}
