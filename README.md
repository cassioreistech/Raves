# WinBot Core

CLI de automação e orquestração determinística para Windows.

## Ambiente

A máquina só possui Python 3.15, incompatível com `pywin32`/`nuitka`. O projeto fixa
**Python 3.12** (`.python-version`), instalado de forma isolada via `uv` — o Python
global não é alterado:

```powershell
python -m pip install uv
python -m uv python install 3.12
python -m uv venv --python 3.12 --seed .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

> `requires-python = ">=3.11,<3.14"`: o teto é a trava de compatibilidade da toolchain
> nativa. Suba a versão só depois de validar o build Nuitka.
>
> Console Windows legado: use `chcp 65001` ou Windows Terminal para acentos em pt-BR.

## Comandos

```powershell
.\.venv\Scripts\winbot.exe --help
.\.venv\Scripts\winbot.exe sys status
.\.venv\Scripts\winbot.exe version

# Workflows — DRY-RUN é o padrão, nada é executado
.\.venv\Scripts\winbot.exe workflow run examples/demo.workflow.yaml
.\.venv\Scripts\winbot.exe workflow list

# Prova da trava de segurança (deve sair com código 1)
.\.venv\Scripts\winbot.exe workflow run examples/bloqueado.workflow.yaml

# Execução real exige --apply E security.allow_shell=true em
# %LOCALAPPDATA%\WinBot\settings.yaml
.\.venv\Scripts\winbot.exe workflow run examples/demo.workflow.yaml --apply

.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
```

## Schema de workflow

```yaml
name: Minha rotina
steps:
  - name: Listar temporários
    action: powershell          # launch_app | kill_process | focus_window | wait
    params:
      command: "Get-ChildItem $env:TEMP"
      timeout: 15
    continue_on_error: false
```

`extra="forbid"` no Pydantic: chave desconhecida é erro, não silêncio.
`wait.seconds` é limitado a 0–60 s. Uma violação de segurança aborta a rotina
**mesmo com `continue_on_error: true`**.

## Segurança

- `core/security.py`: `BLACKLIST_PATTERNS` + `validate_shell_command()`, sem ordem fixa
  de flags e sem exigir `c:\` literal (bloqueia `$env:USERPROFILE`, `D:\`, `~`, `Format-Volume`).
- `engine/shell.py`: `shell=False`, comando em `.ps1` temporário via `-File`, timeout, allowlist.
- `engine/windows_api.py`: `launch_app` **nunca** usa `shell=True`; allowlist de apps e
  denylist de processos críticos do sistema.
- Tudo com `dry_run=True` por padrão; trilha de auditoria em `%LOCALAPPDATA%\WinBot`.

## Estrutura

`src/winbot/` (src-layout). `config/settings.example.yaml` é documentação; os defaults
**empacotados** ficam em `src/winbot/assets/settings.defaults.yaml` e o override do
usuário em `%LOCALAPPDATA%\WinBot\settings.yaml`. Workflows do usuário em
`~/.winbot/workflows/`.

## Status

Passos 1 e 2 executados e validados. Roadmap e decisões em `PLAN.md`.
