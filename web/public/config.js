/**
 * Configuração de runtime — valores de desenvolvimento.
 *
 * Fica em `public/` para o Vite copiar verbatim, sem tentar empacotar.
 * Em produção o entrypoint do nginx SOBRESCREVE este arquivo a partir do
 * ambiente (docker/nginx/entrypoint.sh) — é o que permite a mesma imagem
 * servir hml e prd-poc apontando para APIs diferentes.
 */
window.__CONFIG__ = {
  apiBaseUrl: "http://localhost:8000",
  ambiente: "dev",
};
