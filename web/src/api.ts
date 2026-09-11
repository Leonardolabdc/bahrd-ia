import { config } from "./config";
import type {
  CatalogoDeTeste,
  Desativado,
  Encerrados,
  EquipamentoReincidente,
  EstadoDoModelo,
  EstadoIA,
  Fila,
  Metricas,
  NumeroRemovido,
  Ocorrencia,
  PedidoDeTeste,
  Prontidao,
  ReciboDeTeste,
} from "./tipos";

/**
 * Cliente da API do painel.
 *
 * Um erro de rede aqui não pode virar tela em branco: o painel é ferramenta de
 * plantão. Quem chama recebe a exceção e decide o que mostrar.
 */
async function obter<T>(caminho: string): Promise<T> {
  const cabecalhos: Record<string, string> = { Accept: "application/json" };

  // A API exige este cabeçalho em `/painel/*` quando `PAINEL_TOKEN` está
  // definido. É uma tranca contra acesso anônimo pelo túnel, não autenticação
  // de usuário — um token que viaja no bundle não é segredo para quem abre o
  // navegador. Login de operador está no roteiro (`docs/13-seguranca.md`).
  if (config.painelToken) {
    cabecalhos["X-Painel-Token"] = config.painelToken;
  }

  const resposta = await fetch(`${config.apiBaseUrl}${caminho}`, {
    headers: cabecalhos,
  });
  if (!resposta.ok) {
    if (resposta.status === 401) {
      throw new Error(
        `401 em ${caminho} — o painel não mandou um X-Painel-Token válido. ` +
          `Confira VITE_PAINEL_TOKEN e PAINEL_TOKEN.`,
      );
    }
    throw new Error(`${resposta.status} ${resposta.statusText} em ${caminho}`);
  }
  return (await resposta.json()) as T;
}

/**
 * POST no painel. Só havia GET até 03/09/2026.
 *
 * O corpo de erro é lido antes de virar exceção: a rota de eventos de teste
 * responde 422 e 429 com um `detail` escrito em português, e jogar esse texto
 * fora para mostrar "422 Unprocessable Content" desperdiçaria justamente a
 * parte que a tela existe para dar. Quem está do outro lado não é programador.
 */
async function enviar<T>(caminho: string, corpo: unknown): Promise<T> {
  const cabecalhos: Record<string, string> = {
    Accept: "application/json",
    "Content-Type": "application/json",
  };
  if (config.painelToken) {
    cabecalhos["X-Painel-Token"] = config.painelToken;
  }

  const resposta = await fetch(`${config.apiBaseUrl}${caminho}`, {
    method: "POST",
    headers: cabecalhos,
    body: JSON.stringify(corpo),
  });

  if (!resposta.ok) {
    let detalhe = "";
    try {
      const erro = (await resposta.json()) as { detail?: unknown };
      // 422 do próprio Pydantic vem como lista de objetos, não como texto.
      detalhe = typeof erro.detail === "string" ? erro.detail : "";
    } catch {
      detalhe = "";
    }
    throw new Error(detalhe || `${resposta.status} ${resposta.statusText} em ${caminho}`);
  }
  return (await resposta.json()) as T;
}

export const api = {
  fila: () => obter<Fila>("/painel/fila"),
  ocorrencia: (id: string) => obter<Ocorrencia>(`/painel/ocorrencias/${id}`),
  metricas: () => obter<Metricas>("/painel/metricas"),
  encerrados: () => obter<Encerrados>("/painel/encerrados"),
  desativados: () => obter<Desativado[]>("/painel/desativados"),
  numerosRemovidos: () => obter<NumeroRemovido[]>("/painel/numeros-removidos"),
  reincidencia: () => obter<EquipamentoReincidente[]>("/painel/reincidencia"),
  estado: () => obter<EstadoIA>("/painel/estado"),
  prontidao: () => obter<Prontidao>("/saude/pronto"),

  // A tela de eventos de teste. `catalogoDeTeste` devolve 404 quando a tela
  // está desligada no servidor, e é assim que o painel decide se mostra o
  // botão: a decisão vale no servidor, o front só obedece.
  catalogoDeTeste: () => obter<CatalogoDeTeste>("/painel/testes/catalogo"),
  dispararTeste: (pedido: PedidoDeTeste) =>
    enviar<ReciboDeTeste>("/painel/testes/evento", pedido),

  // Trocar o cérebro vale da PRÓXIMA conversa em diante. Quem já está falando
  // com a IA termina no modelo em que começou.
  modelo: () => obter<EstadoDoModelo>("/painel/testes/modelo"),
  trocarModelo: (modelo: string) =>
    enviar<EstadoDoModelo>("/painel/testes/modelo", { modelo }),
};
