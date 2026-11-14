<#
.SYNOPSIS
    Build de distribuicao do WinBot (Passo 4).

.DESCRIPTION
    1. Compila a CLI com Nuitka (--onefile por padrao; --standalone com -Standalone).
    2. Valida o .exe gerado (versao, --help, licenca/HWID e workflow em DRY-RUN).
    3. Opcionalmente gera o instalador Inno Setup (-Installer).
    4. Assina o .exe e o instalador quando WINBOT_SIGN_PFX / WINBOT_SIGN_PASSWORD existem.

    Sem certificado (decisao D3 pendente) o build continua valido, mas o SmartScreen
    vai alertar o cliente. Use -SkipSign para silenciar o aviso em CI de dev.

.EXAMPLE
    .\scripts\build.ps1
    .\scripts\build.ps1 -Installer -Version 0.1.0
    .\scripts\build.ps1 -Standalone -SkipValidation
#>
[CmdletBinding()]
param(
    [string]$Version,
    [switch]$Standalone,
    [switch]$Installer,
    [switch]$SkipSign,
    [switch]$SkipValidation
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    $py = Join-Path $root ".venv\Scripts\python.exe"
    if (-not (Test-Path $py)) {
        throw "venv ausente em $py. Rode: .\.venv\Scripts\python.exe -m pip install -e '.[dev]'"
    }

    if (-not $Version) {
        $Version = (& $py -c "import tomllib,pathlib;print(tomllib.loads(pathlib.Path('pyproject.toml').read_text(encoding='utf-8'))['project']['version'])").Trim()
    }
    if ($Version -notmatch '^\d+\.\d+\.\d+(\.\d+)?$') { throw "Versao invalida: '$Version'" }

    $buildDir = Join-Path $root "build\winbot"
    $payload = Join-Path $root "dist\winbot"
    $installerOut = Join-Path $root "dist\installer"
    if (Test-Path $buildDir) { Remove-Item -Recurse -Force $buildDir }
    if (Test-Path $payload) { Remove-Item -Recurse -Force $payload }
    New-Item -ItemType Directory -Force -Path $payload | Out-Null

    # Incluidos obrigatorios descobertos pelo smoke (commit a230fb1):
    # pywinauto -> comtypes gera wrappers COM via importlib em runtime, invisivel
    # a analise estatica do Nuitka. Sem isso o .exe compila e quebra em execucao.
    $nuitka = @(
        "-m", "nuitka",
        "--assume-yes-for-downloads",
        "--output-dir=build/winbot",
        "--output-filename=winbot.exe",
        "--include-package=winbot",
        "--include-package=win32com",
        "--include-package=comtypes",
        "--include-package=pywinauto",
        "--include-package=pyautogui",
        "--include-package=pydantic",
        "--include-package=typer",
        "--include-package=rich",
        "--include-package=loguru",
        "--include-package=cryptography",
        "--include-package=pyperclip",
        "--include-distribution-metadata=winbot",
        "--include-data-dir=src/winbot/assets=winbot/assets",
        "--nofollow-import-to=win32com.test,unittest,pytest,doctest,pywinauto.tests",
        "--windows-console-mode=force",
        "--company-name=Cassio Reis Tech",
        "--product-name=WinBot",
        "--file-description=WinBot CLI - Automacao para Windows",
        "--file-version=$Version",
        "--product-version=$Version",
        "--copyright=Copyright (c) 2026 Cassio Reis Tech",
        "--onefile-tempdir-spec={CACHE_DIR}/{COMPANY}/{PRODUCT}/{VERSION}"
    )
    if ($Standalone) { $nuitka += "--standalone" } else { $nuitka += "--onefile" }
    $nuitka += (Join-Path $root "scripts\winbot_entry.py")

    $mode = if ($Standalone) { "standalone" } else { "onefile" }
    Write-Host "==> Nuitka: WinBot $Version ($mode)"
    & $py @nuitka
    if ($LASTEXITCODE -ne 0) { throw "Nuitka falhou (exit $LASTEXITCODE)" }

    if ($Standalone) {
        $distDir = Get-ChildItem -Path $buildDir -Directory -Filter "*.dist" | Select-Object -First 1
        if (-not $distDir) { throw "Pasta .dist nao encontrada em $buildDir" }
        Copy-Item -Path (Join-Path $distDir.FullName "*") -Destination $payload -Recurse -Force
    }
    else {
        $oneExe = Get-ChildItem -Path $buildDir -Filter "winbot.exe" -File -Recurse |
            Select-Object -First 1
        if (-not $oneExe) { throw "winbot.exe nao encontrado em $buildDir" }
        Copy-Item -Path $oneExe.FullName -Destination (Join-Path $payload "winbot.exe") -Force
    }

    $exe = Join-Path $payload "winbot.exe"
    if (-not (Test-Path $exe)) { throw "Payload ausente: $exe" }

    function Invoke-CodeSign([string]$Target) {
        if ($SkipSign) { return }
        $pfx = $env:WINBOT_SIGN_PFX
        $password = $env:WINBOT_SIGN_PASSWORD
        if (-not $pfx -or -not $password) {
            Write-Warning "D3 pendente: sem WINBOT_SIGN_PFX/WINBOT_SIGN_PASSWORD. '$Target' NAO assinado (SmartScreen alertara o cliente)."
            return
        }
        $tool = $env:WINBOT_SIGNTOOL
        if (-not $tool) { $tool = (Get-Command signtool.exe -ErrorAction SilentlyContinue).Source }
        if (-not $tool -or -not (Test-Path $tool)) { throw "signtool.exe nao encontrado (defina WINBOT_SIGNTOOL)" }
        $timestamp = $env:WINBOT_SIGN_TIMESTAMP_URL
        if (-not $timestamp) { $timestamp = "http://timestamp.digicert.com" }
        & $tool sign /f $pfx /p $password /fd SHA256 /td SHA256 /tr $timestamp $Target
        if ($LASTEXITCODE -ne 0) { throw "signtool falhou para $Target (exit $LASTEXITCODE)" }
        Write-Host "    assinado: $Target"
    }

    if (-not $SkipValidation) {
        Write-Host "==> Validando o .exe (imports nativos, metadata e YAML empacotado)"

        function Assert-Winbot([string[]]$Arguments, [string]$Expected) {
            $output = & $exe @Arguments | Out-String
            if ($LASTEXITCODE -ne 0) {
                throw "Falhou: winbot $($Arguments -join ' ') (exit $LASTEXITCODE)`n$output"
            }
            if ($Expected -and $output -notmatch $Expected) {
                throw "Saida inesperada de 'winbot $($Arguments -join ' ')' (esperado /$Expected/):`n$output"
            }
            Write-Host "    OK: winbot $($Arguments -join ' ')"
        }

        Assert-Winbot @("version") ([regex]::Escape($Version))
        Assert-Winbot @("--help") "workflow"
        Assert-Winbot @("license") "HWID"
        Assert-Winbot @("workflow", "run", "examples/demo.workflow.yaml") "OK"
    }

    Invoke-CodeSign $exe

    if ($Installer) {
        $iscc = $env:WINBOT_ISCC
        if (-not $iscc) { $iscc = (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source }
        if (-not $iscc) {
            $default = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
            if (Test-Path $default) { $iscc = $default }
        }
        if (-not $iscc -or -not (Test-Path $iscc)) {
            throw "ISCC.exe (Inno Setup 6) nao encontrado. Instale ou defina WINBOT_ISCC."
        }
        New-Item -ItemType Directory -Force -Path $installerOut | Out-Null
        Write-Host "==> Inno Setup: gerando instalador"
        & $iscc "/DMyAppVersion=$Version" (Join-Path $root "installer.iss")
        if ($LASTEXITCODE -ne 0) { throw "ISCC falhou (exit $LASTEXITCODE)" }

        $setup = Get-ChildItem -Path $installerOut -Filter "*.exe" -File | Select-Object -First 1
        if (-not $setup) { throw "Instalador nao gerado em $installerOut" }
        Invoke-CodeSign $setup.FullName
        Write-Host "==> Instalador: $($setup.FullName)"
    }

    Write-Host "==> BUILD OK  |  versao=$Version  |  modo=$mode  |  payload=$payload"
}
finally {
    Pop-Location
}
