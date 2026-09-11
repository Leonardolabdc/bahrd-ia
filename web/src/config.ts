/**
 * Configuração de runtime do painel.
 *
 * O bundle nunca embute o endereço da API: ele é lido de `window.__CONFIG__`,
 * que o entrypoint do nginx escreve em /config.js a partir do ambiente. É o
 * que permite "uma imagem, todos os ambientes" também no front-end.
 *
 * Em desenvolvimento o Vite não passa pelo nginx, então o fallback usa
 * import.meta.env.
 */

declare global {
  interface Window {
    __CONFIG__?: { apiBaseUrl?: string; ambiente?: string; painelToken?: string };
  }
}

export const config = {
  apiBaseUrl:
    window.__CONFIG__?.apiBaseUrl ||
    (import.meta.env.VITE_API_BASE_URL as string | undefined) ||
    "http://localhost:8000",
  ambiente: window.__CONFIG__?.ambiente || "dev",

  // Enviado em `X-Painel-Token` nas chamadas a `/painel/*`. Vazio é o normal
  // em desenvolvimento: a API só exige quando `PAINEL_TOKEN` está definido.
  painelToken:
    window.__CONFIG__?.painelToken ||
    (import.meta.env.VITE_PAINEL_TOKEN as string | undefined) ||
    "",
};
