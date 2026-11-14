# WinBot Core — Plano de Fundação e Arquitetura Comercial

> **Status:** Passos 1–3 ✅ · Passo 4 implementado (build `--onefile` completo ainda
> não executado ponta a ponta) · `do`/`shell` ✅ · Blindagem Etapa 1 ✅ ·
> RPA Nativo Etapa 2 ✅ · **Áudio Etapa 3 ✅ validada**.
> **Alvo:** CLI de automação Windows, software comercial, entregue como binário.
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
| **4. Build & CI (Final)** | Nuitka `.exe` protegido, Inno Setup, `build.ps1`, `installer.iss`, Actions | `.exe` validado + instalador gerado (local e CI) |
| 5. Distribuição | download, update checker, rollback | instalação limpa em VM sem Python |

## 6. Decisões pendentes

- ✅ D1 CLI/Typer · ✅ D2 automação Windows — definidas.
- **D3** — certificado de assinatura de código? Sem ele, SmartScreen alerta o cliente.
- **D4** — auto-update ou instalador manual por versão?
- **N1** — pasta no disco é `Raves`, produto é `winbot`. Renomear? (não fazer sem confirmação)
- ✅ **N3** — escopo de `limpar temp` definido em `core/dispatcher.py`: só arquivos
  diretos de `%TEMP%`, sem recursão/diretórios/symlinks, ignora arquivos em uso.
- **N4** — `winbot init` para materializar `settings.yaml`, `~/.winbot/workflows/` e instalar licença.
- ✅ **N5** — smoke revalidado: `.exe` de 14,5 MB executa e imprime os imports
  nativos. `--include-package=comtypes` é obrigatório e está no `build.ps1`.
- **N6** — `do`/`shell` executam por padrão (exceção ao dry-run de `workflow run`);
  `--dry-run` simula. Decisão do operador, documentada no README. Confirmar se deve
  voltar ao dry-run por padrão.

## 7. Riscos / validações

- **Nuitka + pywin32/pywinauto/pyautogui/cryptography**: a linkagem C com 206 arquivos
  estourou 15 min na primeira tentativa. Alvo reduzido + `--nofollow-import-to`
  aplicados e **revalidados**: `build/smoke/smoke_entry.exe` roda com exit 0.
  O `build.ps1` do Passo 4 herda os mesmos includes.
- Console Windows cp1252: glifos Unicode (`✔`/`✘`) causam `UnicodeEncodeError`.
  **Corrigido**: `stdout.reconfigure(utf-8)` + fallback ASCII `OK`/`X` quando o
  stream não é UTF-8. `do`/`shell` usam ✔/✘; `workflow run` mantém `OK`/`X`.
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

**Smoke Nuitka (achado importante):** a 1ª compilação gerou
`build/smoke/smoke_entry.exe` (13,2 MB) mas **falhou em runtime** com
`ModuleNotFoundError: No module named 'comtypes.stream'`. Causa: `pywinauto` →
`comtypes` gera wrappers COM via `importlib` em runtime, invisível à análise
estática do Nuitka. Correção aplicada e publicada (`a230fb1`):
`--include-package=comtypes --include-package=pywinauto`. **Revalidação concluída
em 14/11**: `winbot native imports OK: TECH_ONE pyautogui pyperclip pywinauto
win32com 50.0.2`, exit 0. O gate cumpriu seu papel: detectou o problema antes
do Passo 4. (O wrapper de log com `*>&1` + `ErrorActionPreference=Stop` gerava
`NativeCommandError` e abortava antes do `$LASTEXITCODE`; corrigido no script.)

**Abertura do sistema:** bateria funcional completa no terminal real +
janela visível com `winbot rpa spy` aberta (PID 23824, Ctrl+C para fechar).
WezTerm não instalado → abertura via `Start-Process` com argv puro, sem shell.

## 12. Passo 4 + interface de pedidos (14/11)

**Passo 4 (implementado, build completo pendente):** `scripts/winbot_entry.py`
(entry point Nuitka), `scripts/build.ps1` (onefile/standalone, validação do `.exe`,
assinatura opcional, `-Installer`), `installer.iss` (Inno Setup 6, instalação por
usuário com `PrivilegesRequired=lowest` para manter PATH/HKCU e `settings.yaml`
no mesmo perfil), `installer/settings.distribution.yaml` (liga `licensing.enabled`
com `onlyifdoesntexist`), `.github/workflows/ci.yml` e `release.yml`. `installer.iss`
**compila limpo** (ISCC exit 0, sem warnings) com payload temporário. O que falta:
rodar `build.ps1 -Installer` até o fim e assinar (D3).

**Interface `do`/`shell` (implementada e validada):** `core/dispatcher.py` é a
fonte única de execução — `commands/workflow.py` passou a delegar para
`execute_step`, eliminando a duplicação das travas de segurança. Parser
determinístico com 8 verbos, encadeamento por ` e ` com lookahead de verbo,
`digitar ... com enter`, aliases UWP para `fechar calc`, `clean_temp` de escopo
estreito. `main.py` ganhou `do` (ícones ✔/✘ via Rich) e `shell`
(`Prompt.ask("winbot >")`).

**Gates:** `pytest -q` → **100 passed** · `ruff check .` · `ruff format --check .`
· `pyright` → 0 erros · terminal real:

```
> winbot do "abrir calc e esperar 1 segundos e fechar calc"
  ✔ abrir calc.exe App iniciado: calc.exe
  ✔ esperar 1 segundo(s) Aguardou 1.0s
  ✔ fechar calc.exe 2 instancia(s) encerrada(s)
3 ação(ões) concluída(s).     EXIT=0
```

`ps Remove-Item -Recurse ...` → ✘ BLOQUEADO, exit 1 (fail-closed). `shell` com
pipe `abrir calc` + `sair` → ✔ e encerra. `do --dry-run` não dispara efeitos.

## 13. Blindagem · Etapa 1 (14/11) ✅

**Entregue:** `core/database.py` (SQLite em `~/.winbot/winbot.db`, WAL +
`synchronous=NORMAL` em toda conexão, tabelas `installed_apps` / `command_history`,
`upsert_apps` / `find_app` / `log_command` / `get_last_successful_command` /
`get_recent_history` + `count_apps` / `get_apps` / `is_memory_command`);
`engine/app_indexer.py` (199 apps indexados nesta máquina: `.lnk` recursivo dos
dois Start Menu + `App Paths` HKLM/HKCU via `winreg`, sem COM, com limites duros);
`commands/apps.py` (`sync` com spinner, `list --filter`); `main.py` registra
`apps.app`.

**Dispatcher:** auto-index uma vez quando a tabela está vazia; `_resolve_app_name`
= `APP_ALIASES` → `find_app` → raw puro; `repetir`/`faz de novo`/`historico`/
`ultimos comandos`; `log_command` em toda execução; `redact_command` para não
vazar payload de `digitar` no terminal.

**Decisões de segurança registradas:** apps do índice liberam só o próprio
basename via `policy.model_copy` **dentro do dispatcher** — `workflow run` mantém
a allowlist original e um YAML com `params.indexed` não bypassa nada. `.lnk` usa
`os.startfile` com caminho fixo (não é `shell=True`). `raw_command` fica em texto
claro no DB local (necessário para `repetir`), mas `do`/`historico` exibem versão
mascarada. `get_last_successful_command` filtra comandos de memória (anti-loop).

**Gates:** `pytest -q` → **124 passed** · `ruff check .` · `ruff format --check .`
· `pyright` → 0 erros. Terminal real: `apps sync` → 199 apps, `PRAGMA
journal_mode` = `wal`; `do "abrir chrome" --dry-run` resolve o `.exe` do registro;
`repetir` reexecuta o ciclo do calc sem loop; `historico` mostra 5 linhas.

**Testes:** `tests/conftest.py` ganhou fixture `autouse` com `WINBOT_DB_PATH`
isolado em `tmp_path` + `WINBOT_SKIP_APP_INDEX=1`, para nenhum teste tocar no
banco real nem varrer o Windows de verdade.

## 14. RPA Nativo · Etapa 2 (14/11) ✅

**Entregue:** `engine/uia_engine.py` (`wait_for_window` com tenacity 0.5s,
`click_control` com `invoke()`+fallback `click_input()`, `fill_field` com
`set_edit_text()`+fallback clipboard, `list_window_controls`, `foreground_window_title`);
`core/diagnostics.py` (`capture_error_snapshot` → screenshot + `.txt` em
`~/.winbot/crash_reports`); ações `uia_click`, `uia_fill`, `wait_window` no
schema `WorkflowAction` (com validação) e em `_execute_step`; captura automática
de snapshot em toda falha de etapa; comando `winbot rpa inspect <titulo>` com
tabela Rich; parser natural `clicar em <ctrl> na janela <janela>`, `clicar no
botao <ctrl>` (janela ativa) e `esperar janela <titulo>`.

**Gates:** `pytest -q` → **160 passed** · `ruff check .` · `ruff format --check .`
· `pyright` → 0 erros. Terminal real: `rpa inspect Calculadora --depth 8` → 53
controles; `do "clicar em Cinco na janela Calculadora"` → ✔; `do "focar
Calculadora e clicar no botao Seis"` (janela ativa) → ✔; `do "esperar janela
Calculadora"` → ✔.

**Testes:** `tests/test_uia_engine.py` (8), `tests/test_diagnostics.py` (2),
novos casos no dispatcher. `execute_step` agora captura snapshot em exceções e
em resultados False.

## 15. Engenharia de Áudio · Etapa 3 (14/11) ✅

**Entregue:** `core/database.py` ganhou tabelas `speech_corrections` e
`voice_profile` + `save_speech_correction` / `apply_speech_corrections` /
`get_custom_vocab` / `add_custom_vocab` / `get_speech_corrections` /
`get_voice_profile` / `set_voice_profile`. `engine/audio_pipeline.py`
(`ResilientAudioCapture`: ring buffer 1,5s, AGC suave, filtro passa-alta 80 Hz,
auto-recovery de PortAudio, VAD webrtcvad, silêncio adaptativo 0,8/1,5s,
calibração de piso de ruído). `engine/voice.py` (`VoiceEngine`: faster-whisper
com `initial_prompt` dinâmico, TTS pyttsx3 em thread dedicada com barge-in,
`listen_once` com fuzzy match + aprendizado pós-execução, `run_loop`).
`commands/voice_cmd.py` (calibração + listagem do aprendizado fonético) e
`commands/voice.py` (listen + calibrate). Dispatcher: `quando eu disser X entenda Y`,
`aprender palavra X`, `memorizar termo X`. `pyproject.toml`: sounddevice, numpy,
webrtcvad-wheels, faster-whisper, pyttsx3.

**Gates:** `pytest -q` → **160 passed** · `ruff check .` · `ruff format --check .`
· `pyright` → 0 erros. Terminal real: `voice calibrate` calibrou piso de ruído,
capturou 57600 bytes de PCM (3s), montou initial_prompt de 795 chars com apps
indexados; treino via `do` gravou correção `crôme → chrome` e vocabulário
`vé éssi code`, `uatsap`; `apply_speech_corrections('abrir crôme')` →
`'abrir chrome'`; `match_command` retorna candidato com ratio ≥ 0,75; `voice
listen` inicia o observador e encerra limpo em `sair`.

**Decisão honesta registrada:** `voice listen` roda em **modo texto** — Whisper e
pyttsx3 estão instalados e a calibração funciona, mas a captura ao vivo via
`sounddevice` depende de microfone padrão configurado e ASR/TTS real fica para
etapa futura. Nada usa nuvem/API.

---

**Próximo:** rodar `scripts/build.ps1 -Installer` até o fim (compilação onefile
completa, ~20–40 min) e decidir D3 (certificado) e N6 (dry-run padrão em `do`).
Etapa 4 de Blindagem (escopo a definir).
