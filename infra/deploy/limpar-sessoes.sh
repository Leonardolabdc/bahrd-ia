#!/usr/bin/env bash
# ============================================================================
# Apaga as conversas em curso e recomeça do zero.
#
#   ./infra/deploy/limpar-sessoes.sh
#   ./infra/deploy/limpar-sessoes.sh --tudo    (apaga também a janela de 24 h)
#
# Para que serve: testar abre ocorrência de verdade. Uma tentativa que falha na
# ENTREGA deixa a conversa viva assim mesmo — a ocorrência nasce antes de a
# mensagem sair, e é assim de propósito: evento que chegou não pode sumir
# porque o WhatsApp recusou.
#
# O efeito acumula rápido. Com várias conversas vivas do mesmo telefone, a
# resposta da pessoa chega a um sistema que tem N casos abertos para ela, e a
# IA tenta tratar todos no mesmo diálogo. Não é defeito: é o cenário de frota,
# em que um gestor tem vários veículos no mesmo número. Só que aqui os "vários
# veículos" são tentativas de teste.
#
# ⛔ **Não roda em produção.** Apagar conversa viva de quem está falando é
#    exatamente o que o ADR-003 existe para impedir. Aqui a trava é explícita.
# ============================================================================
set -euo pipefail

cd "$(dirname "$0")/../.."
COMPOSE="docker compose -f docker-compose.prod.yml --env-file .env.prod"

AMBIENTE=$(grep -E '^APP_ENV=' .env.prod | cut -d= -f2-)
if [ "$AMBIENTE" = "prd-poc" ]; then
  echo "RECUSADO: este e o ambiente de producao (APP_ENV=$AMBIENTE)." >&2
  echo "          Apagar conversa viva de quem esta falando e o que o ADR-003" >&2
  echo "          existe para impedir. Rode na maquina de desenvolvimento." >&2
  exit 1
fi

TUDO="${1:-}"

echo "═══ limpando conversas · ambiente $AMBIENTE ═══"

antes=$($COMPOSE exec -T redis redis-cli --scan --pattern 'sessao:*' | wc -l)
echo "  conversas vivas antes: $antes"

$COMPOSE exec -T redis sh -c \
  "redis-cli --scan --pattern 'sessao:*' | xargs -r redis-cli del" >/dev/null

if [ "$TUDO" = "--tudo" ]; then
  # A janela de 24 h da Meta é dinheiro: dentro dela a mensagem é livre e
  # gratuita; fora, só template, cobrado por disparo. Só apague se quiser
  # exercitar de propósito o caminho de janela fechada.
  $COMPOSE exec -T redis sh -c \
    "redis-cli --scan --pattern 'janela:*' | xargs -r redis-cli del" >/dev/null
  echo "  janela de 24 h tambem apagada"
fi

# O Redis é o espelho; a memória do processo é a fonte de leitura (ADR-003).
# Sem reiniciar, as conversas continuam vivas dentro da API e voltariam a ser
# gravadas na próxima requisição.
echo "  reiniciando api e worker"
$COMPOSE restart api worker >/dev/null 2>&1

for i in $(seq 1 24); do
  estado=$(docker inspect "$($COMPOSE ps -q api)" --format '{{.State.Health.Status}}' 2>/dev/null || echo "")
  [ "$estado" = "healthy" ] && { echo "  api saudavel apos $((i * 5))s"; break; }
  sleep 5
done

depois=$($COMPOSE exec -T redis redis-cli --scan --pattern 'sessao:*' | wc -l)
echo "  conversas vivas depois: $depois"
echo "═══ pronto ═══"
