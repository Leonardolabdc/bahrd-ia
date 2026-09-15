# ============================================================================
# Front-end — painel do operador (React 19 + TypeScript + Vite + Tailwind).
#
# Dois alvos, porque um SPA não tem como ter paridade total entre dev e prod:
#   dev      → servidor do Vite com HMR (usado pelo docker compose local)
#   runtime  → build estático servido por nginx (a imagem que vai para o OCIR)
#
# A configuração de runtime do SPA chega por /config.js gerado no entrypoint,
# não por variável embutida no bundle — assim a MESMA imagem serve dev, hml e
# prd-poc, apontando para APIs diferentes.
# ============================================================================

# ─────────────────────────── stage 1 · deps ───────────────────────────
FROM node:22-alpine AS deps
WORKDIR /app
COPY web/package.json web/package-lock.json* ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund

# ─────────────────────────── stage 2 · dev ────────────────────────────
FROM node:22-alpine AS dev
WORKDIR /app
ENV NODE_ENV=development
COPY --from=deps /app/node_modules ./node_modules
COPY web/ ./
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]

# ─────────────────────────── stage 3 · build ──────────────────────────
FROM node:22-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY web/ ./
RUN npm run build

# ────────────────────────── stage 4 · runtime ─────────────────────────
FROM nginx:1.27-alpine AS runtime

RUN addgroup -g 10001 app \
 && adduser -u 10001 -G app -S -s /sbin/nologin app \
 && rm -rf /usr/share/nginx/html/*

COPY docker/nginx/painel.conf /etc/nginx/conf.d/default.conf
COPY docker/nginx/entrypoint.sh /usr/local/bin/entrypoint.sh
COPY --from=build /app/dist /usr/share/nginx/html

# nginx precisa escrever em cache/run; porta 8080 para rodar sem root
RUN chmod +x /usr/local/bin/entrypoint.sh \
 && sed -i 's|^pid .*|pid /tmp/nginx.pid;|' /etc/nginx/nginx.conf \
 && chown -R app:app /usr/share/nginx/html /var/cache/nginx /etc/nginx/conf.d

USER app
EXPOSE 8080

# ⚠️ `127.0.0.1`, e não `localhost`.
#
# `listen 8080` no nginx escuta **só em IPv4**. Dentro do contêiner,
# `localhost` resolve primeiro para `::1`, o wget tenta IPv6 e recebe
# "Connection refused" — com o nginx servindo 200 normalmente o tempo todo. O
# sintoma é um contêiner eternamente `unhealthy` que funciona perfeitamente, e
# o `depends_on: service_healthy` de quem depende dele nunca libera.
#
# `/healthz` em vez de `/`: é o endpoint dedicado, com `access_log off`, então
# a sonda não enche o log de uma requisição a cada 15 segundos.
HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3   CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["nginx", "-g", "daemon off;"]
