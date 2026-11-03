<#
.SYNOPSIS
    Abre o Chrome com depuração remota apontando para o servidor local do laboratório.

.DESCRIPTION
    Executado pela tarefa automática do VS Code ao abrir o projeto. Espera o runserver
    responder e então:
      - se já existe um Chrome escutando na porta de depuração, ativa a aba do
        laboratório (ou abre uma nova), sem duplicar janelas;
      - caso contrário, inicia o Chrome com um perfil dedicado.

    O perfil fica fora do repositório. Desde o Chrome 136 a depuração remota só é
    aceita com um --user-data-dir diferente do perfil padrão do usuário.
#>
param(
    [int]$DebugPort = 9997,
    [string]$Url = "http://localhost:8602/",
    [int]$TimeoutSeconds = 60,
    [string]$ProfileDir = (Join-Path $env:LOCALAPPDATA "b2g-lab\chrome-debug-profile")
)

$ErrorActionPreference = "Stop"

function Find-Chrome {
    $candidates = @(
        "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
        "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
        "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
    )
    foreach ($path in $candidates) {
        if (Test-Path $path) { return $path }
    }
    return $null
}

function Test-ServerUp([string]$Target) {
    try {
        Invoke-WebRequest -Uri $Target -UseBasicParsing -TimeoutSec 2 | Out-Null
        return $true
    } catch [System.Net.WebException] {
        # Resposta HTTP de erro (4xx/5xx) também indica que o servidor está no ar
        return $null -ne $_.Exception.Response
    } catch {
        return $false
    }
}

function Test-DebugPortOpen([int]$Port) {
    try {
        Invoke-RestMethod -Uri "http://127.0.0.1:$Port/json/version" -TimeoutSec 2 | Out-Null
        return $true
    } catch {
        return $false
    }
}

# No Windows, "localhost" tenta primeiro o IPv6 (::1) e leva cerca de 2 s para cair
# no IPv4 onde o runserver escuta. A sondagem vai direto em 127.0.0.1.
$probeUrl = $Url -replace "//localhost([:/])", '//127.0.0.1$1'

Write-Host "Aguardando o servidor em $Url ..."
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while (-not (Test-ServerUp $probeUrl)) {
    if ((Get-Date) -gt $deadline) {
        Write-Warning "O servidor não respondeu em $TimeoutSeconds s. Abrindo o Chrome mesmo assim."
        break
    }
    Start-Sleep -Milliseconds 500
}

$devtools = "http://127.0.0.1:$DebugPort"

if (Test-DebugPortOpen $DebugPort) {
    $tabs = Invoke-RestMethod -Uri "$devtools/json/list"
    $labTab = $tabs | Where-Object { $_.type -eq "page" -and $_.url -like "$Url*" } | Select-Object -First 1
    if ($labTab) {
        Invoke-RestMethod -Uri "$devtools/json/activate/$($labTab.id)" | Out-Null
        Write-Host "Chrome de depuração já estava aberto na porta $DebugPort. Aba do laboratório ativada."
    } else {
        Invoke-RestMethod -Method Put -Uri "$devtools/json/new?$Url" | Out-Null
        Write-Host "Chrome de depuração já estava aberto na porta $DebugPort. Nova aba aberta."
    }
    exit 0
}

$chrome = Find-Chrome
if (-not $chrome) {
    Write-Error "Chrome não encontrado. Instale o Google Chrome ou ajuste Find-Chrome neste script."
    exit 1
}

New-Item -ItemType Directory -Force -Path $ProfileDir | Out-Null
Start-Process -FilePath $chrome -ArgumentList @(
    "--remote-debugging-port=$DebugPort",
    "--user-data-dir=`"$ProfileDir`"",
    "--no-first-run",
    "--no-default-browser-check",
    $Url
)
Write-Host "Chrome iniciado com depuração remota em $devtools (perfil: $ProfileDir)."
