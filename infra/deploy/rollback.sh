#!/usr/bin/env bash
# ============================================================================
# Rollback do Bahrd — voltar para a etiqueta anterior.
#
#   ./infra/deploy/rollback.sh              volta para o que deploy.sh guardou
#   ./infra/deploy/rollback.sh v1.0.0       volta para uma etiqueta específica
#
# Este script existe porque uma máquina virtual não tem rollback de plataforma.
# A Vercel guarda cada publicação e promove uma antiga em segundos; aqui não há
# nada guardado além do que nós guardamos. É a consequência ruim registrada no
# ADR-002, e este arquivo é a mitigação dela.
#
# ⚠️ O QUE ESTE SCRIPT **NÃO** DESFAZ: migração de banco.
#
#    Voltar a etiqueta devolve o código, não o schema. Se a versão que está
#    saindo aplicou uma migração destrutiva — renomear coluna, remover tabela —
#    o código antigo volta e encontra um banco que ele não conhece, e o rollback
#    piora a situação em vez de melhorar.
#
#    A regra que torna este script seguro está na disciplina de migração, não
#    aqui: toda migração precisa ser compatível com a versão anterior do
#    código. Adicionar, nunca renomear nem remover na mesma versão. Remover só
#    numa versão seguinte, depois que ninguém mais lê a coluna.
#
#    Antes de rodar isto num incidente real, confira o que a versão que sai
#    migrou:  docker compose ... run --rm migrate alembic history -r<anterior>:
# ============================================================================
set -euo pipefail

cd "$(dirname "$0")/../.."
RAIZ=$(pwd)

ENVFILE="$RAIZ/.env.prod"
ANTERIOR="$RAIZ/.deploy-anterior"
COMPOSE="docker compose -f docker-compose.prod.yml --env-file $ENVFILE"

[[ -f "$ENVFILE" ]] || { echo "ERRO: falta $ENVFILE" >&2; exit 1; }

ALVO="${1:-}"
if [[ -z "$ALVO" ]]; then
  [[ -f "$ANTERIOR" ]] || {
    echo "ERRO: nao ha etiqueta anterior guardada em $ANTERIOR." >&2
    echo "      Passe a etiqueta na mao:  $0 v1.0.0" >&2
    echo "      Disponiveis:" >&2
    docker images --format '        {{.Repository}}:{{.Tag}}' | grep bahrd >&2 || true
    exit 1; }
  ALVO=$(cat "$ANTERIOR")
fi

quebrada=$(grep -E '^IMAGE_TAG=' "$ENVFILE" | cut -d= -f2- || echo "?")

inicio=$(date +%s)
echo "═══ ROLLBACK · $(date -Is) ═══"
echo "  saindo de: $quebrada"
echo "  voltando para: $ALVO"
echo

# A imagem antiga quase sempre ainda está no disco — por isso o rollback é mais
# rápido que o deploy. Se não estiver, o pull busca de novo.
echo "→ garantindo a imagem $ALVO"
sed -i "s|^IMAGE_TAG=.*|IMAGE_TAG=$ALVO|" "$ENVFILE"
$COMPOSE pull api web

echo "→ subindo $ALVO"
$COMPOSE up -d --remove-orphans

echo "→ aguardando"
# A cada 2s. O teto segue 150 segundos — aqui a pressa importa mais que no
# deploy: um rollback acontece com algo quebrado no ar, e cada segundo de
# arredondamento e um segundo a mais de sistema errado atendendo gente.
for i in $(seq 1 75); do
  if docker exec "$($COMPOSE ps -q api)" curl -fsS --max-time 3 \
       http://127.0.0.1:8000/saude/vivo >/dev/null 2>&1; then
    break
  fi
  [[ "$i" -lt 75 ]] || { echo "ERRO: a versao anterior tambem nao subiu"; exit 1; }
  sleep 2
done

# Quem voltou não é mais "o anterior" — o anterior agora é a versão quebrada,
# caso alguém queira ir para frente de novo depois de corrigir.
echo "$quebrada" > "$ANTERIOR"

decorrido=$(( $(date +%s) - inicio ))
echo
echo "═══ ROLLBACK CONCLUIDO em ${decorrido}s ═══"
echo
echo "Conferindo o que ficou no ar:"
# Sem isto o smoke test usa o padrao dele (`prd-poc`) mesmo rodando em dev, e
# dois testes "falham" comparando contra o ambiente errado — nada quebrou, o
# script so nao sabia onde estava.
AMBIENTE_ESPERADO="$(grep -E '^APP_ENV=' "$ENVFILE" | cut -d= -f2- | cut -d'#' -f1 | xargs)" \
  bash tests/smoke/smoke.sh "https://$(grep -E '^DOMINIO=' "$ENVFILE" | cut -d= -f2-)" || {
  echo "⚠️  a versao anterior subiu mas nao passou nos smoke tests."
  exit 1; }
