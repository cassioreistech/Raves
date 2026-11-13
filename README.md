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
.\.venv\Scripts\winbot.exe license              # HWID + status (offline)

# Workflows — DRY-RUN é o padrão, nada é executado
.\.venv\Scripts\winbot.exe workflow run examples/demo.workflow.yaml
.\.venv\Scripts\winbot.exe workflow run examples/rpa.workflow.yaml
.\.venv\Scripts\winbot.exe workflow list

# Prova da trava de segurança (deve sair com código 1)
.\.venv\Scripts\winbot.exe workflow run examples/bloqueado.workflow.yaml

# Agendamento (DRY-RUN por padrão; --apply cria a tarefa)
.\.venv\Scripts\winbot.exe schedule create demo examples/demo.workflow.yaml --at 09:00
.\.venv\Scripts\winbot.exe schedule remove demo

# Inspetor RPA interativo (Ctrl+C para sair)
.\.venv\Scripts\winbot.exe rpa spy

.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
```

Execução real exige `--apply` **e** `security.allow_shell=true` em
`%LOCALAPPDATA%\WinBot\settings.yaml`.

## Schema de workflow

Ações: `powershell`, `launch_app`, `kill_process`, `focus_window`, `wait`,
`gui_click`, `gui_click_image`, `gui_type`, `gui_hotkey`.

```yaml
name: Minha rotina
steps:
  - name: Listar temporários
    action: powershell
    params:
      command: "Get-ChildItem $env:TEMP"
      timeout: 15
    continue_on_error: false
  - name: Clique validado
    action: gui_click
    params: { x: 640, y: 360 }
  - name: Digitar com segurança
    action: gui_type
    params: { text: "texto" }
```

`extra="forbid"` no Pydantic: chave desconhecida é erro. `wait.seconds` é limitado a
0–60 s. Uma violação de segurança aborta a rotina **mesmo com `continue_on_error: true`**.

## Segurança

- `core/security.py`: `BLACKLIST_PATTERNS` + `validate_shell_command()`, sem ordem fixa
  de flags e sem exigir `c:\` literal.
- `engine/shell.py`: `shell=False`, comando em `.ps1` temporário via `-File`, timeout, allowlist.
- `engine/windows_api.py`: `launch_app` **nunca** usa `shell=True`; allowlist de apps e
  denylist de processos críticos.
- `engine/gui.py`: `FAILSAFE` ligado, coordenadas validadas contra a tela, denylist de
  hotkeys (`ctrl+alt+delete`, `alt+f4`…), `gui_type` via clipboard **sem logar o texto**.
- `commands/schedule.py`: nome da tarefa validado por regex, `shell=False`, dry-run.
- Tudo com `dry_run=True` por padrão; auditoria em `%LOCALAPPDATA%\WinBot`.

## Licenciamento (Ed25519, offline)

Ferramenta administrativa — **nunca distribuir**:

```powershell
.\.venv\Scripts\python.exe scripts\keygen.py init
.\.venv\Scripts\python.exe scripts\keygen.py issue --hwid XXXX-XXXX-XXXX-XXXX --days 365
```

- `init` gera o par e injeta a **chave pública** em `core/licensing.py` (entre marcadores).
- A **chave privada** fica em `keys/` e está no `.gitignore` — nunca versionar.
- `issue` emite `WINBOT1.<payload b64>.<assinatura b64>`; instale em
  `%LOCALAPPDATA%\WinBot\license.key`.
- `licensing.enabled` fica `false` em dev; **ligar apenas no build de distribuição**.
- `get_hardware_id()` = SHA-256(nome da máquina + serial do volume), com grace period
  para troca de disco.

> ⚠️ **Limite honesto:** validar com chave pública embutida é contornável por patch no
> binário. Nuitka dificulta, mas a mitigação real é checar em múltiplos pontos do fluxo
> e/ou validação online periódica. O trial de 14 dias é **spoofável** e não é proteção.

## Estrutura

`src/winbot/` (src-layout). `config/settings.example.yaml` é documentação; os defaults
**empacotados** ficam em `src/winbot/assets/settings.defaults.yaml` e o override do
usuário em `%LOCALAPPDATA%\WinBot\settings.yaml`. Workflows do usuário em
`~/.winbot/workflows/`.

## Status

Passos 1, 2 e 3 executados e validados. Roadmap e decisões em `PLAN.md`.
