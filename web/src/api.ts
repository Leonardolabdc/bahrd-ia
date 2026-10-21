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
  SessaoDoPainel,
  Vivo,
} from "./tipos";

/**
 * Cliente da API do painel.
 *
 * Um erro de rede aqui não pode virar tela em branco: o painel é ferramenta de
 * plantão. Quem chama recebe a exceção e decide o que mostrar.
 *
 * **O login mora num cookie `HttpOnly`**, que este código nunca vê: o navegador
 * o guarda e o manda sozinho, desde que cada chamada peça `credentials:
 * "include"`. Sem isso, em desenvolvimento (painel em :5173, API em :8000) o
 * cookie nem seria aceito, e o login pareceria funcionar para cair no primeiro
 * clique.
 */

/** Erro da API com o código HTTP junto, para a tela decidir pelo número. */
export class ErroDaApi extends Error {
  constructor(
    mensagem: string,
    readonly status: number,
  ) {
    super(mensagem);
    this.name = "ErroDaApi";
  }
}

/**
 * A sessão acabou no meio do uso: expirou, alguém saiu em outra aba, ou o
 * usuário foi tirado da configuração. Qualquer 401 de uma rota do painel avisa
 * por este evento, e o `App` volta para o login sem recarregar a página.
 */
const SESSAO_PERDIDA = "bahrd:sessao-perdida";

export function aoPerderASessao(fazer: () => void): () => void {
  window.addEventListener(SESSAO_PERDIDA, fazer);
  return () => window.removeEventListener(SESSAO_PERDIDA, fazer);
}

/** As rotas do próprio login respondem 401 por motivo esperado (senha errada,
 *  ninguém entrou ainda) e quem chama já trata. Não é sessão perdida. */
const ROTA_DA_SESSAO = "/painel/sessao";

function cabecalhos(comCorpo: boolean): Record<string, string> {
  const h: Record<string, string> = { Accept: "application/json" };
  if (comCorpo) h["Content-Type"] = "application/json";

  // A API exige este cabeçalho em `/painel/*` quando `PAINEL_TOKEN` está
  // definido. É a credencial entre a borda e a API, não a de quem usa: em
  // produção quem o injeta é o Caddy, e o navegador nunca o vê. Quem a pessoa é
  // vem do login, pelo cookie.
  if (config.painelToken) {
    h["X-Painel-Token"] = config.painelToken;
  }
  return h;
}

/**
 * O corpo de erro é lido antes de virar exceção: a API responde 401, 403, 422,
 * 429 e 503 com um `detail` escrito em português, e jogar esse texto fora para
 * mostrar "429 Too Many Requests" desperdiçaria justamente a parte que a tela
 * existe para dar. Quem está do outro lado não é programador.
 */
async function detalheDe(resposta: Response): Promise<string> {
  try {
    const erro = (await resposta.json()) as { detail?: unknown };
    // 422 do próprio Pydantic vem como lista de objetos, não como texto.
    return typeof erro.detail === "string" ? erro.detail : "";
  } catch {
    return "";
  }
}

async function chamar(caminho: string, metodo: string, corpo?: unknown): Promise<Response> {
  const resposta = await fetch(`${config.apiBaseUrl}${caminho}`, {
    method: metodo,
    headers: cabecalhos(corpo !== undefined),
    body: corpo === undefined ? undefined : JSON.stringify(corpo),
    credentials: "include",
  });

  if (!resposta.ok) {
    const detalhe = await detalheDe(resposta);

    if (resposta.status === 401 && caminho.startsWith("/painel/") && caminho !== ROTA_DA_SESSAO) {
      window.dispatchEvent(new Event(SESSAO_PERDIDA));
    }

    if (resposta.status === 401 && detalhe.includes("X-Painel-Token")) {
      throw new ErroDaApi(
        `401 em ${caminho} — o painel não mandou um X-Painel-Token válido. ` +
          `Confira VITE_PAINEL_TOKEN e PAINEL_TOKEN.`,
        401,
      );
    }
    throw new ErroDaApi(
      detalhe || `${resposta.status} ${resposta.statusText} em ${caminho}`,
      resposta.status,
    );
  }
  return resposta;
}

async function obter<T>(caminho: string): Promise<T> {
  return (await (await chamar(caminho, "GET")).json()) as T;
}

/** POST no painel. Só havia GET até 03/09/2026. */
async function enviar<T>(caminho: string, corpo: unknown): Promise<T> {
  return (await (await chamar(caminho, "POST", corpo)).json()) as T;
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
  // Sem login: é a sonda de vida do contêiner. A tela de login usa o
  // `ambiente` dela para avisar que não está em produção.
  vivo: () => obter<Vivo>("/saude/vivo"),

  // O login. `entrar` responde 204 e o cookie; quem é vem de `sessaoAtual`.
  // Com o login desligado no servidor (desenvolvimento sem PAINEL_USUARIOS),
  // `sessaoAtual` devolve `login_ativo: false` e o painel abre direto.
  entrar: async (usuario: string, senha: string): Promise<void> => {
    await chamar(ROTA_DA_SESSAO, "POST", { usuario, senha });
  },
  sair: async (): Promise<void> => {
    await chamar(ROTA_DA_SESSAO, "DELETE");
  },
  sessaoAtual: () => obter<SessaoDoPainel>(ROTA_DA_SESSAO),

  // A tela de eventos de teste. `catalogoDeTeste` devolve 404 quando a tela
  // está desligada no servidor, e 403 para o perfil operador: nos dois casos o
  // painel não mostra o botão. A decisão vale no servidor, o front só obedece.
  catalogoDeTeste: () => obter<CatalogoDeTeste>("/painel/testes/catalogo"),
  dispararTeste: (pedido: PedidoDeTeste) =>
    enviar<ReciboDeTeste>("/painel/testes/evento", pedido),

  // Trocar o cérebro vale da PRÓXIMA conversa em diante. Quem já está falando
  // com a IA termina no modelo em que começou.
  modelo: () => obter<EstadoDoModelo>("/painel/testes/modelo"),
  trocarModelo: (modelo: string) =>
    enviar<EstadoDoModelo>("/painel/testes/modelo", { modelo }),
};
