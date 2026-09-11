<#
.SYNOPSIS
    Atalhos do ambiente de desenvolvimento em Docker.

.DESCRIPTION
    Wrapper fino sobre o docker compose. Nada aqui é obrigatório — todo comando
    tem o equivalente direto em `docker compose`, mostrado na ajuda.

.EXAMPLE
    .\dev.ps1 up
    .\dev.ps1 migrate
    .\dev.ps1 logs api
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('setup', 'up', 'down', 'reset', 'build', 'migrate', 'logs',
                 'ps', 'shell', 'test', 'lint', 'saude', 'chaves', 'modelo', 'vozes', 'ajuda')]
    [string]$Comando = 'ajuda',

    [Parameter(Position = 1, ValueFromRemainingArguments)]
    [string[]]$Resto
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

function Invoke-Compose { docker compose @args; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } }

switch ($Comando) {

    'setup' {
        if (Test-Path .env) {
            Write-Host ".env já existe — nada a fazer." -ForegroundColor Yellow
        } else {
            Copy-Item .env.example .env
            Write-Host ".env criado a partir de .env.example." -ForegroundColor Green
            Write-Host "Preencha ANTHROPIC_API_KEY antes do Sprint 1." -ForegroundColor Yellow
        }
    }

    'up'      { Invoke-Compose up -d @Resto }
    'down'    { Invoke-Compose down @Resto }

    'reset' {
        Write-Host "Isso apaga TODOS os volumes (Oracle, MySQL, Redis, MinIO)." -ForegroundColor Red
        $r = Read-Host "Digite 'sim' para confirmar"
        if ($r -ne 'sim') { Write-Host "Cancelado."; break }
        Invoke-Compose down -v
        Write-Host "Volumes apagados. Rode '.\dev.ps1 up' e depois '.\dev.ps1 migrate'." -ForegroundColor Green
    }

    'build'   { Invoke-Compose build @Resto }
    'migrate' { Invoke-Compose run --rm migrate }
    'logs'    { if ($Resto) { Invoke-Compose logs -f @Resto } else { Invoke-Compose logs -f api worker } }
    'ps'      { Invoke-Compose ps }
    'shell'   { Invoke-Compose run --rm shell }

    # O usuário `app` não escreve em /usr/local — daí o --user. As ferramentas
    # de desenvolvimento não entram na imagem: ela é a mesma que vai para a OCI.
    'test'    { Invoke-Compose run --rm --entrypoint sh shell -c "pip install --user -q pytest pytest-asyncio && python -m pytest -q" }
    'lint'    { Invoke-Compose run --rm --entrypoint sh shell -c "pip install --user -q ruff && python -m ruff check --no-cache src migrations tests" }

    # Confere as credenciais sem gastar nada.
    'chaves'  { Invoke-Compose run --rm --entrypoint python shell -m central_ia.diagnostico }

    # Lista as vozes da ElevenLabs com o voice_id de cada uma. Não gasta.
    'vozes'   { Invoke-Compose run --rm --entrypoint python shell -m central_ia.vozes }

    # Teste de fumaça do modelo: 24 tokens de saída, frações de centavo.
    'modelo'  { Invoke-Compose run --rm --entrypoint python shell -m central_ia.agent.diagnostico }

    'saude' {
        try {
            $r = Invoke-RestMethod http://localhost:8000/saude/pronto -TimeoutSec 10
            $r | ConvertTo-Json -Depth 5
        } catch {
            Write-Host "API não respondeu: $_" -ForegroundColor Red
            Write-Host "Verifique com '.\dev.ps1 ps' e '.\dev.ps1 logs api'." -ForegroundColor Yellow
        }
    }

    default {
        @"
POC IA — Central de Monitoramento Bahrd · ambiente de desenvolvimento

  .\dev.ps1 setup      cria o .env a partir do template
  .\dev.ps1 up         sobe a pilha           (docker compose up -d)
  .\dev.ps1 migrate    aplica as migrações    (docker compose run --rm migrate)
  .\dev.ps1 saude      consulta /saude/pronto
  .\dev.ps1 chaves     confere as credenciais de terceiros (não gasta)
  .\dev.ps1 vozes      lista as vozes da ElevenLabs com o voice_id
  .\dev.ps1 modelo     testa a conexão com o modelo (gasta ~US$ 0,0001)
  .\dev.ps1 logs [svc] acompanha os logs      (padrão: api e worker)
  .\dev.ps1 ps         estado dos containers
  .\dev.ps1 shell      bash dentro da imagem real
  .\dev.ps1 test       roda a suíte de testes
  .\dev.ps1 lint       roda o ruff
  .\dev.ps1 build      reconstrói as imagens
  .\dev.ps1 down       derruba (mantém os volumes)
  .\dev.ps1 reset      derruba E apaga os volumes

Endereços locais:
  API .................. http://localhost:8000       (/docs, /saude/pronto)
  Painel ............... http://localhost:5173
  Jaeger (traces) ...... http://localhost:16686
  MinIO (console) ...... http://localhost:9001
"@ | Write-Host
    }
}
