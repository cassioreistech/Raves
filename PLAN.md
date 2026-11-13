# WinBot Core — Plano de Fundação e Arquitetura Comercial

> **Status:** Passos 1, 2 e 3 ✅ executados e validados · **Alvo:** CLI de automação
> Windows, software comercial, entregue como binário Windows.
> **Nota:** o diretório no disco chama-se `Raves`; o produto/pacote é `winbot` (ver N1).

## 1. Decisões tomadas

| Item | Escolha | Justificativa |
|---|---|---|
| Produto | **WinBot** — CLI de automação Windows | D1 = CLI (Typer); D2 = shell + Win32 + GUI/RPA + rotinas YAML |
| Pacote / distro | `src/winbot/` · `winbot` | Produto fechado, sem PyPI |
| Gerenciador | **uv** (provedor do CPython isolado) + `pip install -e` | Máquina só tem 3.15; 3.12 instalado isolado |
| Build backend | **setuptools>=68** | `packages.find where=["src"]`, mais testado com Nuitka |
| Python alvo | **3.12** em `.python-version` | pywin32/Nuitka defasam em CPython novo; `>=3.11,<3.14` |
| Qualidade | **ruff** + **pyright** + **pytest** (+ pytest-mock) | Lint, tipos no VS Code, testes |
| Config | Pydantic v2 + `yaml.safe_load`, `extra="forbid"` | Typos no YAML do cliente viram erro |
| Segurança | `BLACKLIST_PATTERNS` + allowlists + `allow_shell` + dry-run + auditoria | Seção 4.2 |
| Agendamento | **Task Scheduler** (`schtasks`) | Sem elevação/conta SYSTEM, auditável, compatível com `--onefile` |
| Licenciamento | **Ed25519 offline** + HWID + grace period | Chave pública embutida, privada em `keys/` (gitignored) |
| Empacotamento | **Nuitka** (principal) / PyInstaller (protótipo) | Compila nativo e protege o fonte |
| Instalador | **Inno Setup** | Gratuito, maduro, assinatura de código |
| Versionamento | `[project].version` + `importlib.metadata` | Fonte única |

**Deps runtime:** typer, rich, pydantic, PyYAML, loguru, psutil, pywin32, pywinauto,
pyautogui, pyperclip, cryptography.
**Dev:** pytest, pytest-mock, ruff, pyright, build, types-PyYAML, nuitka.

## 2. Árvore real (Passos 1–3)

```
Raves/
├── pyproject.toml · .python-version · .gitignore · README.md · PLAN.md
├── config/settings.example.yaml        # template, sem segredos
├── examples/
│   ├── demo.workflow.yaml
│   ├── rpa.workflow.yaml
│   └── bloqueado.workflow.yaml          # fixture de segurança
├── keys/                                # GITIGNORED: chave privada + licenças emitidas
├── scripts/
│   ├── keygen.py                        # administrativo: init / issue
│   ├── smoke_entry.py · smoke_build.ps1
├── src/winbot/
│   ├── __init__.py · __main__.py · main.py
│   ├── core/
│   │   ├── config.py        # Settings + LicensingSettings + WorkflowStep/Definition
│   │   ├── logger.py        # loguru: arquivo, terminal, auditoria
│   │   ├── security.py      # BLACKLIST_PATTERNS, validate_shell_command, gate
│   │   └── licensing.py     # Ed25519, get_hardware_id(), trial/grace
│   ├── engine/
│   │   ├── shell.py         # run() + run_powershell(), shell=False, -File
│   │   ├── windows_api.py   # snapshot, launch_app, kill_process, focus_window, screen_size
│   │   └── gui.py           # list_windows, focus, click_at, click_image, type_text_safe, hotkey
│   ├── commands/
│   │   ├── system.py        # sys status
│   │   ├── workflow.py      # run / list, Progress + Panel, --apply, 9 ações
│   │   ├── schedule.py      # create / remove via schtasks
│   │   └── rpa_tools.py     # spy (rich.live)
│   └── assets/settings.defaults.yaml   # empacotado via importlib.resources
├── tests/                   # 83 testes
└── dist/winbot-0.1.0-py3-none-any.whl
```

## 3. `pyproject.toml`

- `[project.scripts] winbot = "winbot.main:app"`
- `[tool.setuptools.packages.find] where = ["src"]` · `package-data` inclui `assets/*.yaml`
- `[tool.ruff] extend-exclude = ["build", "dist", "*.egg-info", ".venv"]`
- `[tool.pyright] venvPath/venv = ".venv"`, `reportMissingModuleSource = "none"`

## 4. Proteção de código e segurança operacional

**4.1 Distribuição:** Nuitka `--onefile`, assinatura de código no `.exe` e no instalador,
licenciamento como camada separada, segredos via Windows Credential Manager / DPAPI.

**4.2 Segurança do bot — risco nº 1 do produto**

| Camada | Garantia |
|---|---|
| `BLACKLIST_PATTERNS` | Case-insensitive; **não exige ordem fixa de flags nem `c:\` literal** |
| `validate_shell_command()` | `logger.critical` + `audit()` + `SecurityViolationError` antes de executar |
| `engine/shell.py` | `shell=False`, argv como lista, `.ps1` via `-File`, timeout, allowlist |
| `launch_app` | **Nunca `shell=True`**; rejeita metacaracteres, `shutil.which`, allowlist de apps |
| `kill_process_by_name` | Denylist de processos críticos (`lsass.exe`, `csrss.exe`…) |
| `engine/gui.py` | `FAILSAFE`, coordenadas validadas contra `screen_size()`, denylist de hotkeys, `gui_type` via clipboard com preserção do clipboard e **sem logar o texto** |
| `commands/schedule.py` | Nome da tarefa por regex, `shell=False`, dry-run, aviso de execução sem terminal |
| `dry_run` | Padrão em todas as ações; `--apply` + `security.allow_shell=true` |
| Fail-closed | Step `BLOQUEADO` aborta **mesmo com `continue_on_error: true`** |
| Auditoria | Append-only em `%LOCALAPPDATA%\WinBot\audit.log`, 90 dias |

**4.3 Licenciamento — limite honesto:** validar com chave pública embutida é
**contornável por patch no binário**. Nuitka dificulta, mas a mitigação real é checar
em múltiplos pontos e/ou validação online periódica. O trial de 14 dias é spoofável e
está documentado como conveniência, não proteção. `licensing.enabled=false` em dev;
ligar apenas no build de distribuição.

## 5. Roadmap (redefinido pelo usuário)

| Passo | Entrega | Gate de saída |
|---|---|---|
| **1. Fundação** ✅ | uv/venv, pyproject, src-layout, ruff/pyright/pytest | Seção 9 |
| **2. Motor + Workflows** ✅ | `security.py` → `engine/` → schema YAML → `workflow run/list` | Seção 10 |
| **3. GUI/RPA + Agendamento + Licença** ✅ | `gui.py`, `schedule.py`, `rpa_tools.py`, `licensing.py`, `keygen.py` | Seção 11 |
| **4. Build & CI (Final)** | Nuitka `.exe` protegido, Inno Setup, `build.ps1`, `installer.iss`, Actions | instalador assinado gerado no CI |
| 5. Distribuição | download, update checker, rollback | instalação limpa em VM sem Python |

## 6. Decisões pendentes

- ✅ D1 CLI/Typer · ✅ D2 automação Windows — definidas.
- **D3** — certificado de assinatura de código? Sem ele, SmartScreen alerta o cliente.
- **D4** — auto-update ou instalador manual por versão?
- **N1** — pasta no disco é `Raves`, produto é `winbot`. Renomear? (não fazer sem confirmação)
- **N3** — `commands/system.py` menciona "limpeza": precisa de escopo explícito.
- **N4** — `winbot init` para materializar `settings.yaml`, `~/.winbot/workflows/` e instalar licença.
- **N5** — `smoke_build.ps1` ainda em validação (linkagem C lenta); definir se o Passo 4
  usa `--onefile` completo ou alvo reduzido.

## 7. Riscos / validações

- **Nuitka + pywin32/pywinauto/pyautogui/cryptography**: a linkagem C com 206 arquivos
  estourou 15 min na primeira tentativa. Alvo reduzido + `--nofollow-import-to`
  aplicados; validação em andamento. Não deixar para o Passo 4 sem prova.
- Console Windows cp1252: glifos Unicode (`✔`/`✘`) causam `UnicodeEncodeError`.
  **Corrigido**: símbolos ASCII + `stdout.reconfigure(encoding="utf-8")`.
- Testes com `CliRunner` usam StringIO UTF-8: **não** detectam bugs de codepage.
  Validar sempre também no terminal real.
- `Raves\Raves\` (cópia acidental do repo) causou `import file mismatch` no pytest;
  movido para `%TEMP%\opencode\` sem deletar.
- Rich `Console()`/`Progress` não devem ser lintados em `build/lib` → `extend-exclude`.
- src-layout exige `pip install -e .`; sem isso `import winbot` falha.
- `--onefile` aumenta startup (extração em temp): medir antes de prometer UX.

## 8. Critérios de aceite do Passo 1 ✅

`pip install -e` · pytest · ruff · pyright · `build --wheel` com assets ·
`winbot --help` / `version` / `python -m winbot` · imports nativos · nenhum segredo no tree.

## 9. Registro de execução do Passo 1 ✅

Só Python 3.15 → CPython **3.12.16** isolado via `uv`. `uv venv --seed` +
`pip install -e ".[dev]"`. Ajustes: setuptools, `name="winbot"`, `>=3.11,<3.14`,
`typer` sem `[all]`, +loguru/psutil/pywinauto, `logger.py` sem side-effect no import,
`%SYSTEMDRIVE%`, versão via `importlib.metadata`, defaults em `src/winbot/assets/`,
`venvPath`/`venv` no pyright.

## 10. Registro de execução do Passo 2 ✅

**3 furos graves corrigidos** ante a especificação recebida:
`Popen(cmd, shell=True)` (injeção pelo YAML) → `shell=False` + metacaracteres + allowlist;
blacklist com `c:\` literal/ordem fixa → lookaheads case-insensitive; ausência de
dry-run → `dry_run=True` + `--apply`.

**API adotada:** `SecurityViolationError`, `validate_shell_command()`,
`CommandResult.success/return_code`, `WorkflowDefinition/WorkflowStep` com `params`,
5 ações, `~/.winbot/workflows`, `workflow list`, `Progress` + `Panel`.

**Achados de validação:** `UnicodeEncodeError` com `✔`/`✘` em cp1252 e `ruff` lintando
`build/lib/**`. Ambos corrigidos. Gates: 58 passed, pyright 0 errors, wheel, demo em
DRY-RUN e bloqueio com exit code 1.

## 11. Registro de execução do Passo 3 ✅

**Deps:** `pyautogui 0.9.54`, `pyperclip 1.11`, `cryptography 50.0.2` adicionadas e
instaladas.

**Entregue:** `gui.py` (`click_at`, `click_image`, `type_text_safe`, `hotkey`, mantendo
`list_windows`/`focus_window`); 4 novas ações no schema e no `workflow.py`;
`schedule.py` (`create`/`remove` via `schtasks`, shell=False, nome validado);
`rpa_tools.py` (`spy` com `rich.live`); `licensing.py` (Ed25519, `get_hardware_id()`,
trial, grace); `scripts/keygen.py` (`init`/`issue`); `main.py` com `schedule`, `rpa` e
`license`.

**Decisões de segurança adicionais:** `FAILSAFE` sempre ligado; coordenadas validadas
contra `screen_size()`; denylist de hotkeys perigosos; `gui_type` preserva o clipboard
e **nunca loga o texto** (pode ser senha); `keys/` no `.gitignore`; trial documentado
como spoofável; aviso explícito de que licença local é contornável por patch.

**Keygen executado de verdade:** par Ed25519 gerado, chave pública injetada entre
marcadores em `licensing.py`, chave privada em `keys/` (ignorada). Licença de teste
emitida e verificada ponta a ponta: `LICENSED pro 2027-11-13`, HWID
`7256-9B12-7E90-C611`.

**Gates — todos verdes:** `pytest -q` → **83 passed** · `ruff check .` ·
`ruff format --check .` · `pyright` → 0 errors · `build --wheel` → 17 módulos ·
`winbot license` (TRIAL em dev) · `workflow run examples/rpa.workflow.yaml` (3 steps OK
em DRY-RUN) · `schedule create/remove` (simulados) · `winbot workflow run
examples/bloqueado.workflow.yaml` → BLOQUEADO, exit 1.

**Pendente:** `scripts/smoke_build.ps1` — compilação Nuitka em background, ainda na
linkagem C do gcc 15.2. Resultado a confirmar antes do Passo 4.

---

**Próximo:** Passo 4 (Final) — Nuitka `.exe` protegido + instalador Inno Setup.
