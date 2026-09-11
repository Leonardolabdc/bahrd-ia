# Publica os modelos de mensagem na Meta.
#
# A Meta so deixa editar um modelo ativo UMA VEZ a cada 24 h. Por isso este
# script existe: junta todas as mudancas de cada modelo num envio so, em vez de
# gastar a cota do dia numa correcao de cada vez.
#
#   .\infra\templates-whatsapp\enviar.ps1            edita os que ja existem
#   .\infra\templates-whatsapp\enviar.ps1 -Criar     cria tambem os novos
#
# Duas operacoes diferentes, e e de proposito que a segunda precise ser pedida:
#
#   EDITAR  POST /v26.0/{id_do_modelo}                 corpo sem 'name'
#   CRIAR   POST /v26.0/{waba_id}/message_templates    corpo com 'name'
#
# Modelo com "criar": true no manifesto ainda nao existe na Meta e por isso nao
# tem id. Sem o -Criar ele e pulado: uma correcao de rotina num modelo antigo
# nao pode publicar de carona um modelo que ninguem mandou publicar.
#
# Criar nao mexe em nada que esta no ar. Os modelos antigos seguem funcionando
# enquanto os novos estao em analise, e se a Meta reprovar, nada quebrou.
#
# Le o token do .env. Nao gera cobranca: criar e editar modelo e gratuito.

# -Somente limita a rodada a nomes especificos. Existe porque a lista cresceu:
# com oito modelos no manifesto, ajustar um gastava a cota de edicao de 24 h
# dos outros sete -- e, com modelos em analise no meio, pedia edicao de coisa
# que a Meta ainda nem aprovou. Nomes separados por virgula.
#
#   .\infra\templates-whatsapp\enviar.ps1 -Somente evento_panico_mapa
param([switch]$Criar, [string[]]$Somente)

$ErrorActionPreference = "Stop"
$WABA_ID = "931502646668768"
$raiz = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$env_path = Join-Path $raiz ".env"

$token = (Get-Content $env_path | Where-Object { $_ -match "^META_ACCESS_TOKEN=" } |
          Select-Object -First 1) -replace "^META_ACCESS_TOKEN=", ""
if (-not $token) { throw "META_ACCESS_TOKEN nao encontrado em $env_path" }

# A lista vem do manifesto, nao daqui. A aplicacao le o MESMO arquivo para
# saber o texto que o cliente recebeu (integrations/mensageria/modelos.py) —
# duas listas divergiriam na primeira edicao de modelo.
$manifesto = Get-Content (Join-Path $PSScriptRoot "modelos.json") -Raw -Encoding UTF8 | ConvertFrom-Json
$modelos = $manifesto.modelos

foreach ($m in $modelos) {
  if ($Somente -and ($m.nome -notin $Somente)) {
    Write-Host ("{0,-36} pulado - fora do -Somente" -f $m.nome)
    continue
  }
  $novo = [bool]$m.criar

  # -Criar cria os novos e NAO mexe nos antigos. Aprendido na marra em
  # 26/08/2026: a primeira versao editava os seis de carona e queimou a cota de
  # edicao de 24 h de todos eles numa rodada que so queria criar dois.
  if ($Criar -ne $novo) {
    $motivo = if ($novo) { "novo, rode com -Criar" } else { "ja existe, rode sem -Criar" }
    Write-Host ("{0,-36} pulado - {1}" -f $m.nome, $motivo)
    continue
  }

  # O '_leia' e comentario para quem abre o arquivo; a Meta rejeita campo que
  # nao conhece. Sai aqui, e o resto do arquivo vai como esta.
  $j = Get-Content (Join-Path $PSScriptRoot $m.arquivo) -Raw -Encoding UTF8 | ConvertFrom-Json
  $j.PSObject.Properties.Remove("_leia")

  if ($novo) {
    $uri = "https://graph.facebook.com/v26.0/$WABA_ID/message_templates"
  } else {
    # Editar nao aceita 'name' nem 'language': o nome de um modelo e imutavel.
    $j.PSObject.Properties.Remove("name")
    $j.PSObject.Properties.Remove("language")
    $uri = "https://graph.facebook.com/v26.0/" + $m.id
  }

  $corpo = $j | ConvertTo-Json -Depth 20
  Write-Host ("{0,-36} " -f $m.nome) -NoNewline
  try {
    $r = Invoke-RestMethod -Method Post `
      -Uri $uri `
      -Headers @{ Authorization = "Bearer $token" } `
      -ContentType "application/json; charset=utf-8" `
      -Body ([System.Text.Encoding]::UTF8.GetBytes($corpo))
    if ($novo) {
      Write-Host ("OK - criado, id " + $r.id + " (" + $r.status + ")")
      Write-Host ("  -> anote o id no modelos.json e troque 'criar' por 'id'")
    } elseif ($r.success) {
      Write-Host "OK - em analise"
    } else {
      Write-Host "resposta inesperada"
    }
  } catch {
    # O ErrorDetails.Message vem VAZIO no PowerShell 5.1 para varios erros da
    # Graph API, e um "FALHOU -" seco nao diz nada. O motivo real so aparece
    # lendo o corpo da resposta, entao le-se o corpo.
    $msg = $_.ErrorDetails.Message
    if (-not $msg) {
      try {
        $fluxo = $_.Exception.Response.GetResponseStream()
        $fluxo.Position = 0
        $msg = (New-Object System.IO.StreamReader($fluxo)).ReadToEnd()
      } catch { $msg = $_.Exception.Message }
    }
    Write-Host "FALHOU"
    try {
      $e = ($msg | ConvertFrom-Json).error
      # error_user_msg e a frase em portugues que explica o que corrigir; o
      # 'message' generico ("Invalid parameter") nao ajuda ninguem.
      if ($e.error_user_title) { Write-Host ("  " + $e.error_user_title) }
      if ($e.error_user_msg)   { Write-Host ("  " + $e.error_user_msg) }
      if (-not $e.error_user_msg) { Write-Host ("  " + $e.message) }
    } catch { Write-Host ("  " + $msg) }
  }
}

Write-Host ""
Write-Host "Acompanhar:"
Write-Host "  GET /931502646668768/message_templates?fields=name,status,category"
