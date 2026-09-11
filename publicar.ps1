<#
.SYNOPSIS
    Publica as imagens no OCI Container Registry (OCIR).

.DESCRIPTION
    Marco de mitigação do Sprint 1 (doc 02 §3.4): publicar a primeira imagem no
    OCIR cedo, quando descobrir problema de registry e credencial é barato.

    Constrói os alvos de PRODUÇÃO — `runtime` no back-end e no front-end. O
    alvo `dev` do front-end (servidor do Vite) nunca vai para o registry.

    Autenticação: `docker login <regiao>.ocir.io` com usuário
    `<namespace>/<usuario>` e um **auth token** da OCI como senha (não a senha
    da conta). Ver docs/06-deploy-oci.md §2.

.PARAMETER Versao
    Etiqueta da versão. Padrão: data + hora (ex.: 2026.08.11-1942).

.PARAMETER Regiao
    Chave da região do OCIR. Padrão: gru (São Paulo). Vinhedo: vcp.

.PARAMETER Namespace
    Namespace do object storage do tenancy. Obrigatório.

.PARAMETER Repositorio
    Prefixo dos repositórios no OCIR. Padrão: bahrd-ia.

.PARAMETER SomenteConstruir
    Constrói e etiqueta, sem enviar. Útil para validar antes de ter credencial.

.EXAMPLE
    .\publicar.ps1 -Namespace grxxxxxxxxx
    .\publicar.ps1 -Namespace grxxxxxxxxx -Versao 0.2.0 -Regiao vcp
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Namespace,
    [string]$Versao      = (Get-Date -Format "yyyy.MM.dd-HHmm"),
    [string]$Regiao      = "gru",
    [string]$Repositorio = "bahrd-ia",
    [switch]$SomenteConstruir
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$registry = "$Regiao.ocir.io/$Namespace/$Repositorio"

$alvos = @(
    @{ Nome = "backend"; Dockerfile = "docker/backend.Dockerfile"; Target = "runtime" },
    @{ Nome = "web";     Dockerfile = "docker/web.Dockerfile";     Target = "runtime" }
)

Write-Host "Registry : $registry" -ForegroundColor Cyan
Write-Host "Versão   : $Versao"   -ForegroundColor Cyan
Write-Host ""

foreach ($alvo in $alvos) {
    $comVersao = "$registry/$($alvo.Nome):$Versao"
    $comLatest = "$registry/$($alvo.Nome):latest"

    Write-Host "→ construindo $($alvo.Nome)" -ForegroundColor Green
    docker build `
        --file $alvo.Dockerfile `
        --target $alvo.Target `
        --tag $comVersao `
        --tag $comLatest `
        --platform linux/amd64 `
        .
    if ($LASTEXITCODE -ne 0) { throw "falha ao construir $($alvo.Nome)" }

    if ($SomenteConstruir) {
        Write-Host "  (etiquetado, sem envio)" -ForegroundColor Yellow
        continue
    }

    Write-Host "→ enviando $comVersao" -ForegroundColor Green
    docker push $comVersao
    if ($LASTEXITCODE -ne 0) { throw "falha ao enviar $($alvo.Nome). Fez `docker login $Regiao.ocir.io`?" }
    docker push $comLatest
}

Write-Host ""
Write-Host "Pronto. Imagens publicadas com a versão $Versao." -ForegroundColor Green
Write-Host "Aponte o deploy para as etiquetas COM VERSÃO, nunca para :latest —" -ForegroundColor Yellow
Write-Host "sem isso, não existe rollback determinístico." -ForegroundColor Yellow
