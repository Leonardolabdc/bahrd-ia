#!/usr/bin/env bash
# ============================================================================
# Deploy do Bahrd. Roda NA MÁQUINA, chamado por SSH pelo GitHub Actions.
#
#   ./infra/deploy/deploy.sh <tag-da-imagem>
#   ./infra/deploy/deploy.sh sha-a1b2c3d
#
# O que ele faz, nesta ordem, e por quê:
#
#   1. guarda a etiqueta que está no ar   ← sem isso não existe rollback
#   2. baixa as imagens novas             ← antes de derrubar qualquer coisa
#   3. aplica as migrações                ← com o código NOVO, nunca o antigo
#   4. sobe                               ← `up -d` recria só o que mudou
#   5. espera ficar saudável
#
# ⚠️ Migração não volta com a imagem. Voltar a etiqueta devolve o código, não o
#    schema. Por isso toda migração deste projeto precisa ser compatível com a
#    versão anterior do código — adicionar coluna, nunca renomear nem remover
#    numa versão só. Está registrado na auditoria, lacuna 7.
# ============================================================================
set -euo pipefail

cd "$(dirname "$0")/../.."
RAIZ=$(pwd)

TAG="${1:-}"
[[ -n "$TAG" ]] || { echo "uso: $0 <tag-da-imagem>" >&2; exit 2; }
[[ "$TAG" != "latest" ]] || {
  echo "ERRO: 'latest' nao identifica versao nenhuma, e sem isso o rollback" >&2
  echo "      deixa de existir. Use a etiqueta por commit ou por versao." >&2
  exit 2; }

ENVFILE="$RAIZ/.env.prod"
ANTERIOR="$RAIZ/.deploy-anterior"
COMPOSE="docker compose -f docker-compose.prod.yml --env-file $ENVFILE"

[[ -f "$ENVFILE" ]] || { echo "ERRO: falta $ENVFILE (copie de .env.prod.example)" >&2; exit 1; }

inicio=$(date +%s)
echo "═══ deploy $TAG · $(date -Is) ═══"

# ── 1. Guardar o que está no ar, antes de mexer ─────────────────────────────
atual=$(grep -E '^IMAGE_TAG=' "$ENVFILE" | cut -d= -f2- || true)
if [[ -n "$atual" && "$atual" != "$TAG" ]]; then
  echo "$atual" > "$ANTERIOR"
  echo "→ no ar agora: $atual  (guardado para rollback)"
else
  echo "→ no ar agora: ${atual:-nada}"
fi

# ── 2. Baixar antes de derrubar ─────────────────────────────────────────────
echo "→ baixando imagens $TAG"
sed -i "s|^IMAGE_TAG=.*|IMAGE_TAG=$TAG|" "$ENVFILE"
$COMPOSE pull api web

# ── 3. Migrações, com o código novo ─────────────────────────────────────────
echo "→ migracoes"
$COMPOSE --profile ferramentas run --rm migrate

# ── 4. Subir ────────────────────────────────────────────────────────────────
echo "→ subindo"
$COMPOSE up -d --remove-orphans

# ── 5. Esperar ficar saudável ───────────────────────────────────────────────
# Pergunta a cada 2s, e nao a cada 10s. O teto continua o mesmo — 300 segundos
# —, entao o comportamento diante de uma API que realmente nao sobe nao muda.
#
# O que muda e o arredondamento: com passo de 10s, uma API pronta aos 22s so
# era notada aos 30s, e esses 8 segundos entravam no tempo do pipeline duas
# vezes, uma por ambiente. A rubrica mede o pipeline abaixo de 5 minutos, e ele
# estava a 6 segundos do limite.
echo "→ aguardando healthcheck"
inicio_espera=$(date +%s)
for i in $(seq 1 150); do
  if curl -fsS --max-time 3 http://127.0.0.1:8000/saude/vivo >/dev/null 2>&1 \
     || docker exec "$($COMPOSE ps -q api)" curl -fsS --max-time 3 http://127.0.0.1:8000/saude/vivo >/dev/null 2>&1; then
    echo "  api respondeu apos $(( $(date +%s) - inicio_espera ))s"
    break
  fi
  [[ "$i" -lt 150 ]] || { echo "ERRO: api nao respondeu em 300s"; $COMPOSE logs --tail=50 api; exit 1; }
  sleep 2
done

# Imagem velha ocupa disco, e a maquina gratuita tem 47 GB. Mantem as ultimas.
docker image prune -f --filter "until=168h" >/dev/null 2>&1 || true

echo "═══ deploy concluido em $(( $(date +%s) - inicio ))s · $TAG ═══"
