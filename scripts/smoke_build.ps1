# Gate antecipado: prova que a toolchain Nuitka compila pywin32/pywinauto/pyautogui/
# cryptography. O alvo é mínimo de propósito: a linkagem C cresce rápido com cada import.
# Primeira execução baixa MinGW64 (~100 MB) e pode levar bastante tempo.
#
# --include-package=comtypes é OBRIGATÓRIO: pywinauto -> comtypes gera wrappers COM
# via importlib em runtime. Sem isso o .exe compila mas falha com
# "ModuleNotFoundError: No module named 'comtypes.stream'".
$ErrorActionPreference = "Stop"
$py = ".\.venv\Scripts\python.exe"

& $py -c "import win32api, win32com, pywinauto, pyautogui, pyperclip, cryptography; print('imports nativos OK')"
if ($LASTEXITCODE -ne 0) { throw "Falha nos imports nativos" }

if (Test-Path build\smoke) { Remove-Item -Recurse -Force build\smoke }

& $py -m nuitka --onefile --assume-yes-for-downloads `
    --output-dir=build/smoke --remove-output `
    --include-package=win32com `
    --include-package=comtypes `
    --include-package=pywinauto `
    --nofollow-import-to=win32com.test,unittest,pytest,doctest,pywinauto.tests `
    scripts\smoke_entry.py
if ($LASTEXITCODE -ne 0) { throw "Nuitka nao compilou" }

& .\build\smoke\smoke_entry.exe
if ($LASTEXITCODE -ne 0) { throw "exe nao executou" }

Write-Host "smoke_build OK -> build\smoke\smoke_entry.exe"
