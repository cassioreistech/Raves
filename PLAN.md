# WinBot Core — Plano de Fundação e Arquitetura Comercial

> **Status:** Passos 1 e 2 ✅ executados e validados · **Alvo:** CLI de automação Windows,
> software comercial, entregue como binário Windows.
> **Nota:** o diretório no disco chama-se `Raves`; o produto/pacote é `winbot` (ver N1).

## 1. Decisões tomadas

| Item | Escolha | Justificativa |
|---|---|---|
| Produto | **WinBot** — CLI de automação Windows | D1 = CLI (Typer); D2 = shell + Win32 + GUI + rotinas YAML |
| Pacote / distro | `src/winbot/` · `winbot` | Produto fechado, sem PyPI |
| Gerenciador | **uv** (provedor do CPython isolado) + `pip install -e` | Máquina só tem 3.15; 3.12 instalado isolado |
| Build backend | **setuptools>=68** | `packages.find where=["src"]`, mais testado com Nuitka |
| Python alvo | **3.12** em `.python-version` | pywin32/Nuitka defasam em CPython novo; `>=3.11,<3.14` |
| Qualidade | **ruff** + **pyright** + **pytest** (+ pytest-mock) | Lint, tipos no VS Code, testes |
| Config | Pydantic v2 + `yaml.safe_load`, `extra="forbid"` | Typos no YAML do cliente viram erro |
| Segurança | `BLACKLIST_PATTERNS` + allowlists + `allow_shell` + dry-run + auditoria | Ver seção 4.2 |
| Empacotamento | **Nuitka** (principal) / PyInstaller (protótipo) | Nuitka compila nativo e protege o fonte |
| Instalador | **Inno Setup** | Gratuito, maduro, assinatura de código |
| Versionamento | `[project].version` + `importlib.metadata` | Fonte única |
| GUI | pywinauto p/ descoberta, Win32 nativo p/ foco | pyautogui é extra opcional `gui` |

**Deps runtime:** typer, rich, pydantic, PyYAML, loguru, psutil, pywin32, pywinauto.
**Dev:** pytest, pytest-mock, ruff, pyright, build, types-PyYAML, nuitka.

## 2. Árvore real (Passos 1 + 2)

```
Raves/
├── pyproject.toml · uv.lock(não usado) · .python-version · .gitignore
├── README.md · PLAN.md
├── config/settings.example.yaml        # template, sem segredos
├── examples/
│   ├── demo.workflow.yaml
│   └── bloqueado.workflow.yaml          # fixture de segurança
├── src/winbot/
│   ├── __init__.py · __main__.py · main.py
│   ├── core/
│   │   ├── config.py        # Settings + WorkflowStep/WorkflowDefinition
│   │   ├── logger.py        # loguru: arquivo, terminal, auditoria (sem side-effect no import)
│   │   └── security.py      # BLACKLIST_PATTERNS, validate_shell_command, gate
│   ├── engine/
│   │   ├── shell.py         # run() + run_powershell(), shell=False, -File
│   │   ├── windows_api.py   # system_snapshot, launch_app, kill_process, focus_window
│   │   └── gui.py           # list_windows (pywinauto) + delegação de foco
│   ├── commands/
│   │   ├── system.py        # sys status (psutil + Rich)
│   │   └── workflow.py      # run / list, Progress + Panel, --apply
│   └── assets/settings.defaults.yaml   # empacotado via importlib.resources
├── tests/                   # 58 testes
├── scripts/smoke_entry.py · scripts/smoke_build.ps1
└── dist/winbot-0.1.0-py3-none-any.whl
```

## 3. `pyproject.toml`

- `[project.scripts] winbot = "winbot.main:app"`
- `[tool.setuptools.packages.find] where = ["src"]` · `package-data` inclui `assets/*.yaml`
- `[tool.ruff] extend-exclude = ["build", "dist", "*.egg-info", ".venv"]`
- `[tool.pyright] venvPath/venv = ".venv"`, `reportMissingModuleSource = "none"`
- `[project.optional-dependencies] gui = ["pyautogui>=0.9.54"]`

## 4. Proteção de código e segurança operacional

**4.1 Distribuição:** Nuitka `--onefile` (sem `.pyc` solto), assinatura de código no
`.exe` e no instalador, licenciamento como camada separada (Passo 4), segredos via
Windows Credential Manager / DPAPI.

**4.2 Segurança do bot — risco nº 1 do produto**

| Camada | Garantia |
|---|---|
| `BLACKLIST_PATTERNS` | Case-insensitive; **não exige ordem fixa de flags nem `c:\` literal**. Cobre `Remove-Item $env:USERPROFILE -Recurse -Force`, `-Force -Recurse D:\`, `Format-Volume`, `diskpart`, `bcdedit`, `Invoke-Expression`, `Stop-Computer`, `reg delete`, `vssadmin delete shadows`… |
| `validate_shell_command()` | API pública: `logger.critical` + `audit()` + `SecurityViolationError` antes de qualquer execução |
| `engine/shell.py` | `shell=False`, argv como lista, `.ps1` temporário via `-File` (sem `-Command` interpolado), timeout obrigatório, allowlist de executáveis |
| `launch_app` | **Nunca `shell=True`**; rejeita metacaracteres `& \| ; < > ^`, valida `shutil.which`, allowlist `allowed_apps` |
| `kill_process_by_name` | Denylist de processos críticos (`lsass.exe`, `csrss.exe`, `explorer.exe`…) |
| `dry_run` | Padrão em todas as ações; `--apply` explícito + `security.allow_shell=true` |
| Fail-closed | Step `BLOQUEADO` aborta a rotina **mesmo com `continue_on_error: true`** |
| Auditoria | Append-only em `%LOCALAPPDATA%\WinBot\audit.log`, 90 dias |

## 5. Roadmap (redefinido pelo usuário)

| Passo | Entrega | Gate de saída |
|---|---|---|
| **1. Fundação** ✅ | uv/venv, pyproject, src-layout, ruff/pyright/pytest, smoke | Seção 9 |
| **2. Motor + Workflows** ✅ | `security.py` → `engine/` → schema YAML → `workflow run/list` | Seção 10 |
| 3. Licenciamento | ativação, verificação offline, anti-tamper | licença inválida bloqueia sem crash |
| 4. Build & CI | `build.ps1`, `installer.iss`, Actions `windows-latest`, `smoke_build.ps1` | instalador assinado gerado no CI |
| 5. Distribuição | download, update checker, rollback | instalação limpa em VM sem Python |

## 6. Decisões pendentes

- ✅ **D1** CLI/Typer · ✅ **D2** automação Windows — definidas.
- **D3** — possui certificado de assinatura de código? Sem ele, SmartScreen alerta o cliente.
- **D4** — auto-update ou instalador manual por versão?
- **N1** — pasta no disco é `Raves`, produto é `winbot`. Renomear? (não fazer sem confirmação)
- **N3** — `commands/system.py` menciona "limpeza": precisa de escopo explícito antes de
  qualquer ação destrutiva.
- **N4** — `winbot init` para materializar `settings.yaml` e `~/.winbot/workflows/`.

## 7. Riscos / validações

- **Validar Nuitka + pywin32/pywinauto já com `smoke_build.ps1`** — único gate do Passo 1
  ainda não executado (baixa MinGW64 ~100 MB). Deixar para o Passo 4 é o erro mais caro.
- Console Windows cp1252: glifos Unicode (`✔`/`✘`) causam `UnicodeEncodeError`.
  **Corrigido**: símbolos ASCII + `stdout.reconfigure(encoding="utf-8")`.
- Rich `Console()` e `Progress` não devem ser lintados em `build/lib` → `extend-exclude`.
- Testes com `CliRunner` usam StringIO UTF-8: **não** detectam bugs de codepage. Validar
  sempre também no terminal real.
- src-layout exige `uv run` / `pip install -e .`; sem isso `import winbot` falha.
- `--onefile` aumenta startup (extração em temp): medir antes de prometer UX.

## 8. Critérios de aceite do Passo 1 ✅

`uv sync`/`pip install -e` · pytest · ruff · pyright · `build --wheel` com assets ·
`winbot --help` / `version` / `python -m winbot` · imports nativos pywin32/pywinauto ·
nenhum segredo no tree.

## 9. Registro de execução do Passo 1 ✅

Ambiente: só Python 3.15 → instalado CPython **3.12.16** isolado via `uv`, sem tocar no
global. `uv venv --seed` (o venv do uv não vem com pip) + `pip install -e ".[dev]"`.

Ajustes ante o plano original (instrução posterior prevaleceu): setuptools em vez de
hatchling; `name = "winbot"`; `>=3.11,<3.14`; `typer` sem `[all]` (extra removido no Typer
moderno); +loguru/psutil/pywinauto; `logger.py` sem side-effect no import; unidade via
`%SYSTEMDRIVE%`; versão via `importlib.metadata`; `config/` virou template e os defaults
foram para `src/winbot/assets/`; `venvPath`/`venv` no pyright.

Instalados: Nuitka 4.3.5, pywin32 312, pywinauto 0.6.9, typer 0.29.1, rich 15.0.0.

## 10. Registro de execução do Passo 2 ✅

O usuário enviou uma especificação completa. Foram **corrigidos 3 furos graves** antes de
adotá-la:

| # | Código enviado | Correção |
|---|---|---|
| 1 | `subprocess.Popen(cmd, shell=True)` em `launch_app` | Injeção de comando direta pelo YAML → `shell=False`, rejeição de metacaracteres, `shutil.which` e allowlist |
| 2 | Blacklist exigia `c:\` literal e `-recurse` antes de `-force` | `Remove-Item $env:USERPROFILE -Recurse -Force` e `-Force -Recurse D:\` passavam → padrões com lookahead, case-insensitive, sem path literal |
| 3 | Nenhum dry-run | `kill_process`/`launch_app`/`focus_window` agiam ao rodar → `dry_run=True` em tudo, `--apply` explícito |

**API adotada do usuário:** `SecurityViolationError`, `validate_shell_command()`,
`CommandResult.success/return_code`, `WorkflowDefinition`/`WorkflowStep` com `params` e
`continue_on_error`, ações `powershell | launch_app | kill_process | focus_window | wait`,
`~/.winbot/workflows`, `workflow run <nome>`, `workflow list`, `Progress` + `Panel`.

**Garantias preservadas:** `HARD_DENY`, allowlist de executáveis, `allow_shell`,
auditoria append-only, fail-closed (bloqueio ignora `continue_on_error`), `extra="forbid"`,
teto de 60 s em `wait`.

**Achados de validação corrigidos:** `UnicodeEncodeError` com `✔`/`✘` em console cp1252
(trocados por `OK`/`X` + UTF-8 no stdout) e `ruff` lintando `build/lib/**`
(`extend-exclude`). Os testes com `CliRunner` não pegavam nenhum dos dois.

**Gates — todos verdes:** `pytest -q` → **58 passed** · `ruff check .` ·
`ruff format --check .` · `pyright` → 0 errors · `build --wheel` → 14 módulos + assets ·
`winbot workflow run examples/demo.workflow.yaml` (DRY-RUN, 4 steps OK) ·
`winbot workflow run examples/bloqueado.workflow.yaml` → `BLOQUEADO`, **exit code 1**,
step seguinte não executado · `winbot workflow list` · `winbot sys status` · `winbot --help`.

**Pendente:** `scripts/smoke_build.ps1` (compilação Nuitka real, baixa MinGW64).

---

**Próximo:** `smoke_build.ps1`, `winbot init` (N4) ou Passo 3 (licenciamento).
