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

## Pedidos em linguagem natural (`do` / `shell`)

Sem YAML e sem LLM: `core/dispatcher.py` mapeia cada frase por regex para uma ação
do engine. A cadeia usa ` e ` como separador, mas só quebra quando depois dele vem
um verbo conhecido — `digitar João e Maria` continua sendo um único texto.

```powershell
.\.venv\Scripts\winbot.exe do "abrir calc e esperar 1 segundos e fechar calc"
.\.venv\Scripts\winbot.exe do "digitar Olá com enter e atalho ctrl+v" --dry-run
.\.venv\Scripts\winbot.exe shell          # loop até 'sair' / 'exit' / Ctrl+C
```

| Pedido | Ação |
|---|---|
| `abrir <app>` | `launch_app` (allowlist; `calc` → `calc.exe`) |
| `fechar <app>` | `kill_process` (denylist) |
| `focar <janela>` | `focus_window` por substring do título |
| `digitar <texto>` | `gui_type` via clipboard; sufixo ` com enter` dispara `Enter` |
| `atalho <teclas>` | `gui_hotkey` — aceita `ctrl+c`, `ctrl + v` |
| `limpar temp` | `clean_temp` |
| `esperar <N> segundos` | `wait` (0–60 s, validado pelo schema) |
| `ps <comando>` | `powershell` via `.ps1` temporário |

**Diferença importante:** ao contrário de `workflow run` (dry-run por padrão),
`do` e `shell` **executam imediatamente** — o pedido digitado é a autorização
explícita do operador. Use `--dry-run` para simular. Todas as travas continuam
ativas: allowlists, denylist de processos/hotkeys, `FAILSAFE`, blacklist,
auditoria e fail-closed (para no primeiro ✘/bloqueio). `ps` só roda de fato com
`security.allow_shell=true`; sem isso é bloqueado.

Escopo de **`limpar temp`** (decisão N3): apenas arquivos regulares **diretos** de
`%TEMP%`; sem recursão, sem diretórios, sem symlinks, ignora arquivos em uso.
Nunca toca nas pastas `onefile_*` do binário Nuitka.

`fechar calc` testa aliases explícitos (`Calculator.exe` / `CalculatorApp.exe`):
no Windows 10/11 o `calc.exe` é apenas um stub. O texto de `digitar` nunca aparece
no rótulo nem em log (pode ser senha). Ícones ✔/✘ em UTF-8, com fallback ASCII
`OK`/`X` em consoles cp1252 que não aceitarem o reconfigure.

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

## Build de distribuição (Passo 4)

```powershell
# .exe onefile validado em dist\winbot\winbot.exe
.\scripts\build.ps1

# .exe + instalador Inno Setup em dist\installer\WinBotSetup-<versao>.exe
.\scripts\build.ps1 -Installer -Version 0.1.0
```

`build.ps1` compila `scripts/winbot_entry.py` com Nuitka, valida o binário
(`version`, `--help`, `license`, um workflow em DRY-RUN) e, com `-Installer`,
chama `ISCC.exe` sobre `installer.iss`. O instalador coloca o `.exe` em
`{autopf}\WinBot`, adiciona a pasta ao PATH (opcional), cria o atalho
*WinBot Console* e instala `licensing.enabled: true` em
`%LOCALAPPDATA%\WinBot\settings.yaml` **somente se o arquivo não existir**.

Variáveis de ambiente do build:

| Variável | Uso |
|---|---|
| `WINBOT_ISCC` | caminho do `ISCC.exe` (detectado automaticamente) |
| `WINBOT_SIGN_PFX` / `WINBOT_SIGN_PASSWORD` | assinam `.exe` e instalador via `signtool` |
| `WINBOT_SIGNTOOL` | caminho do `signtool.exe` |
| `WINBOT_SIGN_TIMESTAMP_URL` | servidor de timestamp (padrão DigiCert) |

> Sem certificado (**D3** pendente) o build é válido, mas o SmartScreen alerta
> o cliente. `-SkipSign` silencia o aviso em CI de desenvolvimento.
>
> `-Standalone` troca `--onefile` por pasta `.dist` (startup mais rápido); o
> `installer.iss` empacota os dois formatos sem alteração.

CI: `.github/workflows/ci.yml` roda os gates em todo push/PR; `release.yml`
roda em tags `v*` e gera o instalador como artifact. O segredo
`WINBOT_SIGN_PFX_BASE64` + `WINBOT_SIGN_PASSWORD` habilita a assinatura no CI.

## Status

Passos 1, 2 e 3 executados e validados. Passo 4 implementado, em validação local. Roadmap e decisões em `PLAN.md`.
