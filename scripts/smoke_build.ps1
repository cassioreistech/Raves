# Gate antecipado do Passo 1: prova que a toolchain Nuitka compila pywin32/pywinauto.
# Requer compilador C (Nuitka baixa MinGW64 ~100 MB na primeira execução).
$ErrorActionPreference = "Stop"
$py = ".\.venv\Scripts\python.exe"

& $py -c "import win32api, win32com, pywinauto, psutil, typer, rich, loguru; print('imports nativos OK')"
if ($LASTEXITCODE -ne 0) { throw "Falha nos imports nativos" }

& $py -m nuitka --onefile --standalone --assume-yes-for-downloads `
    --output-dir=build/smoke --remove-output `
    --include-package=win32com `
    scripts\smoke_entry.py
if ($LASTEXITCODE -ne 0) { throw "Nuitka nao compilou" }

Write-Host "smoke_build OK -> build\smoke\smoke_entry.exe"
