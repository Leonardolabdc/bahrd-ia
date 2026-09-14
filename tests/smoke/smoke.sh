#!/usr/bin/env bash
# ============================================================================
# Smoke tests do Bahrd — a verificação que roda DEPOIS do deploy.
#
# Não substitui a suíte: os 953 testes provam que o código está certo, estes
# três provam que o que está no ar é o que deveria estar, e que ele alcança o
# que precisa alcançar. São coisas diferentes, e a segunda só dá para verificar
# de fora.
#
#   ./tests/smoke/smoke.sh https://bahrd.duckdns.org
#   VERSAO_ESPERADA=1.0.0 AMBIENTE_ESPERADO=prd-poc ./tests/smoke/smoke.sh <url>
#
# Sai com 0 se os três passarem, 1 se qualquer um falhar. É esse código de saída
# que o CD usa para decidir entre seguir e fazer rollback.
# ============================================================================
set -uo pipefail

BASE="${1:-${BASE_URL:-}}"
VERSAO_ESPERADA="${VERSAO_ESPERADA:-}"
AMBIENTE_ESPERADO="${AMBIENTE_ESPERADO:-prd-poc}"
TIMEOUT="${TIMEOUT:-15}"

if [[ -z "$BASE" ]]; then
  echo "uso: $0 <url-base>   (ex.: https://bahrd.duckdns.org)" >&2
  exit 2
fi
BASE="${BASE%/}"

falhas=0
n=0

vermelho() { printf '\033[31m%s\033[0m\n' "$1"; }
verde()    { printf '\033[32m%s\033[0m\n' "$1"; }

# Executa um teste. $1 nome, $2 descrição do que ele prova, resto: comando.
teste() {
  local nome="$1" prova="$2"; shift 2
  n=$((n + 1))
  local inicio fim ms
  inicio=$(date +%s%3N)
  local saida
  if saida=$("$@" 2>&1); then
    fim=$(date +%s%3N); ms=$((fim - inicio))
    verde "  PASSOU  [$n/3] $nome  (${ms}ms)"
    echo   "          prova: $prova"
    [[ -n "$saida" ]] && echo "          $saida"
  else
    fim=$(date +%s%3N); ms=$((fim - inicio))
    vermelho "  FALHOU  [$n/3] $nome  (${ms}ms)"
    echo     "          prova: $prova"
    echo     "          $saida"
    falhas=$((falhas + 1))
  fi
}

# ─────────────────────────────────────────────────────────────────────────────
# 1 · O processo está de pé, e é a versão que acabamos de publicar.
#
# Só "responde 200" não serve: um deploy que falhou deixa a versão ANTERIOR
# respondendo 200 alegremente. Conferir a versão é o que transforma esta sonda
# em prova de que o deploy pegou.
# ─────────────────────────────────────────────────────────────────────────────
t1_vivo() {
  local corpo
  corpo=$(curl -fsS --max-time "$TIMEOUT" "$BASE/saude/vivo") || {
    echo "GET /saude/vivo nao respondeu 2xx"; return 1; }

  echo "$corpo" | grep -q '"status":"vivo"' || {
    echo "status != vivo: $corpo"; return 1; }

  local versao ambiente
  versao=$(echo "$corpo"   | sed -n 's/.*"versao":"\([^"]*\)".*/\1/p')
  ambiente=$(echo "$corpo" | sed -n 's/.*"ambiente":"\([^"]*\)".*/\1/p')

  if [[ -n "$VERSAO_ESPERADA" && "$versao" != "$VERSAO_ESPERADA" ]]; then
    echo "no ar esta a versao '$versao', esperava '$VERSAO_ESPERADA' — o deploy nao pegou"
    return 1
  fi
  if [[ "$ambiente" != "$AMBIENTE_ESPERADO" ]]; then
    echo "ambiente '$ambiente', esperava '$AMBIENTE_ESPERADO'"
    return 1
  fi
  echo "versao=$versao ambiente=$ambiente"
}

# ─────────────────────────────────────────────────────────────────────────────
# 2 · As três dependências respondem de dentro da nuvem.
#
# É o único teste que prova que a fiação da OCI está certa: o wallet do
# Autonomous Database, a rota para a sub-rede privada do HeatWave e o Redis.
# Nenhuma dessas três coisas dá para verificar do notebook.
# ─────────────────────────────────────────────────────────────────────────────
t2_pronto() {
  local corpo http
  corpo=$(curl -sS --max-time "$TIMEOUT" -w '\n%{http_code}' "$BASE/saude/pronto") || {
    echo "GET /saude/pronto nao respondeu"; return 1; }
  http=$(echo "$corpo" | tail -1)
  corpo=$(echo "$corpo" | sed '$d')

  if [[ "$http" != "200" ]]; then
    echo "HTTP $http — alguma dependencia caiu: $corpo"
    return 1
  fi
  echo "$corpo" | grep -q '"status":"pronto"' || {
    echo "status != pronto: $corpo"; return 1; }

  local dep
  for dep in oracle mysql redis; do
    echo "$corpo" | grep -q "\"$dep\":{\"ok\":true}" || {
      echo "dependencia '$dep' nao respondeu: $corpo"; return 1; }
  done
  echo "oracle, mysql e redis responderam"
}

# ─────────────────────────────────────────────────────────────────────────────
# 3 · O painel é servido, com TLS válido e apontando para o ambiente certo.
#
# `curl` sem `-k`: um certificado inválido reprova aqui, e não no navegador do
# avaliador. E o `config.js` é gerado no boot a partir das variáveis de
# ambiente — conferi-lo é conferir que elas chegaram configuradas na máquina.
# ─────────────────────────────────────────────────────────────────────────────
t3_painel() {
  local http
  http=$(curl -sS --max-time "$TIMEOUT" -o /dev/null -w '%{http_code}' "$BASE/") || {
    echo "GET / nao respondeu (TLS invalido?)"; return 1; }
  [[ "$http" == "200" ]] || { echo "GET / devolveu HTTP $http"; return 1; }

  local cfg
  cfg=$(curl -fsS --max-time "$TIMEOUT" "$BASE/config.js") || {
    echo "config.js nao foi servido — o painel nao sabe qual API chamar"; return 1; }

  echo "$cfg" | grep -q "ambiente: \"$AMBIENTE_ESPERADO\"" || {
    echo "config.js nao declara ambiente '$AMBIENTE_ESPERADO': $cfg"; return 1; }

  # https:// sem -k ja provou o certificado; registra a validade para o log.
  local dias
  dias=$(curl -sS --max-time "$TIMEOUT" -o /dev/null -w '%{certs}' "$BASE/" 2>/dev/null \
         | sed -n 's/^Expire date: *//p' | head -1)
  echo "painel servido, TLS valido${dias:+, certificado expira em $dias}"
}

# ─────────────────────────────────────────────────────────────────────────────
echo
echo "Smoke tests · $BASE"
echo "ambiente esperado: $AMBIENTE_ESPERADO${VERSAO_ESPERADA:+ · versao esperada: $VERSAO_ESPERADA}"
echo

teste "liveness e versao no ar" \
      "o deploy pegou, e quem responde e a versao que acabou de subir" t1_vivo

teste "readiness das dependencias" \
      "Autonomous Database, MySQL HeatWave e Redis respondem de dentro da OCI" t2_pronto

teste "painel, TLS e variaveis de ambiente" \
      "o SPA e servido sob certificado valido e sabe em que ambiente esta" t3_painel

echo
if [[ "$falhas" -eq 0 ]]; then
  verde "3/3 passaram."
  exit 0
fi
vermelho "$falhas de 3 falharam."
echo "O CD trata isto como gatilho de rollback: infra/deploy/rollback.sh"
exit 1
