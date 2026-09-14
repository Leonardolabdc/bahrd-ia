#!/bin/sh
# ============================================================================
# Gera /config.js no boot a partir das variáveis de ambiente.
#
# É isso que permite "uma imagem, todos os ambientes" no front-end: o bundle
# nunca embute o endereço da API. O SPA lê window.__CONFIG__ em runtime.
# ============================================================================
set -eu

: "${APP_ENV:=dev}"
: "${VITE_API_BASE_URL:=}"

cat > /usr/share/nginx/html/config.js <<EOF
window.__CONFIG__ = {
  apiBaseUrl: "${VITE_API_BASE_URL}",
  ambiente: "${APP_ENV}"
};
EOF

exec "$@"
