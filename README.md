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

## RPA Nativo · Etapa 2 (Windows UI Automation + Tenacity)

Automação **por nome acessível**, não por coordenada: funciona com janela
redimensionada/movida e em monitores com escalas DPI diferentes. Tudo com
retentativas (`tenacity`) e diagnóstico automático em falha.

```powershell
.\.venv\Scripts\winbot.exe rpa inspect Calculadora --depth 8
.\.venv\Scripts\winbot.exe do "clicar em Cinco na janela Calculadora"
.\.venv\Scripts\winbot.exe do "focar Calculadora e clicar no botao Dois"
.\.venv\Scripts\winbot.exe do "esperar janela Calculadora"
```

Ações de workflow (schema validado): `uia_click`, `uia_fill`, `wait_window`.
Quando uma etapa falha, `core/diagnostics.py` grava screenshot + `.txt` em
`~/.winbot/crash_reports` (100% local; screenshot pode falhar em sessão RDP).

Motor `engine/uia_engine.py`:
- `wait_for_window(title, timeout=15)` — tenacity (0.5s, até timeout)
- `click_control(window, control, control_type=None)` — `invoke()` com fallback
  `click_input()`
- `fill_field(window, field, text, press_enter=False)` — `set_edit_text()` com
  fallback clipboard (acentos PT-BR)
- `list_window_controls(window, max_depth=3)` — tabela Rich via
  `winbot rpa inspect`
- `foreground_window_title()`

## System Tray · Etapa 4 (execução em segundo plano)

```powershell
.\.venv\Scripts\winbot.exe tray
```

Roda o WinBot discretamente ao lado do relógio do Windows (ícone gerado em
memória, sem arquivo externo). Menu: **Ativar/Pausar Voz**, **Abrir Shell**,
**Executar Workflow** (submenu com os YAMLs de `~/.winbot/workflows`) e **Sair**.
O observador de contexto sobe em background; `CREATE_NEW_CONSOLE` abre o shell em
janela separada sem `shell=True`.

## Engenharia de Áudio · Etapa 3 (STT/TTS offline, barge-in, aprendizado fonético)

Pipeline de voz 100% offline. Nenhuma rede, nenhum modelo em nuvem.

```powershell
.\.venv\Scripts\winbot.exe voice calibrate
.\.venv\Scripts\winbot.exe voice listen
.\.venv\Scripts\winbot.exe do "quando eu disser crôme entenda chrome"
.\.venv\Scripts\winbot.exe do "aprender palavra vé éssi code"
.\.venv\Scripts\winbot.exe do "memorizar termo uatsap"
```

Camadas (`engine/audio_pipeline.py` + `engine/voice.py`):
- Ring buffer de pré-roll (1,5s) + AGC suave + filtro passa-alta 80 Hz
- Auto-recovery de PortAudio (fone desconectado/trocado): reabre o stream sem
  fechar o programa
- VAD neural (webrtcvad) em vez de RMS bruto
- Silêncio adaptativo: frases curtas cortam em ~0,8s, longas aguardam ~1,5s
- `initial_prompt` dinâmico no faster-whisper: apps indexados + vocabulário
  customizado + correções fonéticas já aprendidas
- TTS (pyttsx3/SAPI5) em thread dedicada com **barge-in**: se você começar a
  falar por cima, o robô cala imediatamente
- Aprendizado pós-execução: transcrição levemente distorcida + comando executado
  com sucesso → par gravado em `speech_corrections` (fuzzy match ≥ 0,75)

Banco (`~/.winbot/winbot.db`):
- `speech_corrections(heard_phrase PK, mapped_phrase, hits, updated_at)`
- `voice_profile(key PK, value)`

Comandos naturais: `quando eu disser X entenda Y`, `aprender palavra X`,
`memorizar termo X`. `apply_speech_corrections` roda antes do dispatcher, então
a correção é instantânea na próxima vez. `redact_command` mascara payloads de
`digitar` na exibição.

> **Status atual:** `voice listen` **usa ASR/TTS reais** quando o modelo Whisper
> `tiny` está no cache local (`~/.cache/huggingface`) e há microfone padrão:
> captura, transcreve, executa e fala a resposta (com barge-in). Caso contrário,
> cai automaticamente para modo texto, sem erro. O modelo `tiny` (~75 MB) é
> baixado automaticamente na primeira `voice calibrate`/`voice listen`. Nada usa
> nuvem/API.

## Sprint A · Visão/OCR Nativo + Gravador Inteligente

Motor de visão (`engine/vision.py`) usa WinRT OCR nativo do Windows 10/11
(`Windows.Media.Ocr`) com fallback para `rapidocr-onnxruntime`. Captura a janela
ativa por padrão (3x mais rápido, menos RAM) ou uma região.

```powershell
.\.venv\Scripts\winbot.exe do "ler tela"
.\.venv\Scripts\winbot.exe do "clicar no texto OK"
.\.venv\Scripts\winbot.exe flow record minha_rotina   # grava cliques -> YAML
```

`engine/recorder.py` — `WorkflowRecorder` monitora cliques do mouse (pynput) e,
no exato momento de cada clique esquerdo, consulta o controle UIA sob o cursor
para gerar um passo semântico (`uia_click`), caindo para `gui_click` apenas se
não houver controle acessível. ESC/Ctrl+C encerra e salva o YAML em
`~/.winbot/workflows/<nome>.yaml`.

Ação de workflow nova: `ocr_click` (com `text`). `ler tela`/`o que esta escrito
na tela` lê a janela ativa via OCR e exibe/fala um resumo (truncado a 500
chars). `clicar no texto <texto>` executa `vision.click_text`.

## Sprint B · Gatilhos Reativos + Cérebro Híbrido (Ollama)

Gatilhos event-driven em ~0% CPU (sem polling):

```powershell
.\.venv\Scripts\winbot.exe trigger list
.\.venv\Scripts\winbot.exe trigger add --name pdf_novo --event file_created --path "$HOME\Downloads" --ext .pdf --run organizar_pdfs
.\.venv\Scripts\winbot.exe trigger add --name calc_abriu --event window_opened --window Calculadora --run "focar Calculadora"
.\.venv\Scripts\winbot.exe trigger watch       # Ctrl+C encerra
```

`file_created` usa `watchdog` (ReadDirectoryChangesW nativo) com debounce de 1,5s
(para o download terminar). `window_opened` reusa uma única thread de polling de
baixa frequência (2s). O daemon também sobe dentro de `winbot tray`.

Cérebro híbrido (`ai/local_brain.py`): Ollama local (modelo leve, ex.
`qwen2.5:1.5b`) com `keep_alive: "2m"` (RAM liberada após 2 min de ociosidade),
comunicação via `urllib` (sem SDK). `is_available()` tem cache de 60s e timeout
de 0,3s — se o Ollama não estiver instalado, degrada graciosamente. O
`initial_prompt` injeta interesses do usuário + comandos válidos; se a pergunta
mencionar área de transferência, inclui `pyperclip.paste()` (truncado a 2000
chars).

Roteador em cascata no dispatcher: parser determinístico (1 ms) → memória/hábitos
→ LocalBrain (se `ACTION: <comando>` executa; senão resposta conversacional) →
fallback amigável offline com dicas.

## Blindagem · Etapa 6 (Contexto de Sessão, Normalizador, Risco 3 Níveis)

Contexto de sessão em memória (`core/session.py`): `last_target_app`,
`last_window_title`, `last_entities`. Referências anafóricas:

```powershell
.\.venv\Scripts\winbot.exe do "abrir notepad e digitar ola mundo e fechar isso" --yes
```

`abrir notepad` seta o alvo; `digitar` foca a janela automaticamente; `fechar isso`
resolve para `notepad.exe`. `fechar ele` / `fechar janela` também funcionam.

Normalizador de linguagem coloquial (antes do parser, preserva aspas):
`por favor abrir calc agora` → `abrir calc`.

Comandos de perfil 100% offline:
- `tocar musica` / `bota uma musica` / `colocar minha musica`: consulta
  `user_interests` (categoria `musica`); se aprendeu um estilo (ex.: `lofi`),
  abre o player/navegador preferido (com busca no YouTube para navegadores);
  senão, abre o player padrão indexado.
- `preparar meu ambiente` / `modo trabalho`: executa a rotina de maior
  confiança para o `hour_bucket` atual.

Classificação de risco em 3 níveis (`core/security.py`):
- **GREEN** (imediato): abrir, focar, ler tela, status, histórico, insights,
  esperar, tocar música, digitar.
- **YELLOW** (confirmação rápida se interativo): fechar, RPA/UIA/OCR, cliques.
- **RED** (confirmação explícita): limpar temp, `ps`, kill em massa.

`winbot do` ganhou `--yes`/`-y` para automação sem prompt. No `shell`, confirmação
`[s/N]` via Rich; no `voice listen`, o robô pergunta em voz e escuta
"sim"/"pode fazer"/"confirmo" vs "não"/"cancela".

## Cérebro Local · Ollama (setup zero-atrito)

O WinBot gerencia o ciclo de vida do Ollama automaticamente — não precisa ficar
rodando na inicialização do Windows.

```powershell
.\.venv\Scripts\winbot.exe ai status
.\.venv\Scripts\winbot.exe ai setup          # instala Ollama (winget) + baixa qwen2.5:1.5b
.\.venv\Scripts\winbot.exe ai setup --lite    # qwen2.5:0.5b (397 MB, PCs com 4 GB)
.\.venv\Scripts\winbot.exe ai unload         # descarrega o modelo da RAM agora
.\.venv\Scripts\winbot.exe ai shutdown       # encerra o serve se foi o WinBot que subiu
```

Quando o `LocalBrain` precisa responder e a porta 11434 está fechada, o WinBot
sobe `ollama serve` em segundo plano (`CREATE_NO_WINDOW`) com
`OLLAMA_MAX_LOADED_MODELS=1` e `OLLAMA_NUM_PARALLEL=1`, aguarda até 3s e depois
envia a requisição com `keep_alive: "90s"`, `num_ctx: 1024`, `num_predict: 140`.
Após 90s de ociosidade o modelo é descarregado da RAM. Se o Ollama não estiver
instalado, degrada graciosamente (fallback offline com dicas).

## Blindagem · Etapa 1 (SQLite WAL, índice de apps, memória)

Banco local em `~/.winbot/winbot.db` (`WINBOT_DB_PATH` permite isolar em testes).
**Toda** conexão aplica `PRAGMA journal_mode=WAL` e `PRAGMA synchronous=NORMAL`.
Tabelas criadas na inicialização: `installed_apps(name PK, target_path, source,
updated_at)` e `command_history(id, raw_command, success, result_message,
executed_at)`.

```powershell
.\.venv\Scripts\winbot.exe apps sync                # varre Menu Iniciar + App Paths
.\.venv\Scripts\winbot.exe apps list --filter chrome
```

O indexador (`engine/app_indexer.py`) lê `.lnk` recursivamente dos dois
`Start Menu\Programs` (ignorando `uninstall`/`remover`), mais as chaves
`HKLM`/`HKCU ...\App Paths` via `winreg`. Normaliza em minúsculo (`Google
Chrome.lnk` → `google chrome`) e gera alias curto (`googlechrome`). **Sem COM nem
ShellExecute na varredura**, limites duros e falhas ignoradas por item — não trava
a CLI. Registro tem prioridade sobre `.lnk` (entrega o `.exe` real).

Se `installed_apps` estiver vazia, o primeiro `do`/`shell` indexa **uma vez**
automaticamente. `_resolve_app_name` consulta `APP_ALIASES` → `database.find_app`
(exato, depois `LIKE` pelo nome mais curto) → raw puro.

Comandos de memória (valem sozinhos, não em cadeia):

| Pedido | Efeito |
|---|---|
| `repetir` / `repetir ultimo` / `faz de novo` | reexecuta o último comando bem-sucedido |
| `historico` / `ultimos comandos` | exibe os últimos 5 |

Toda execução é registrada. `repetir` não entra em loop: comandos de memória são
filtrados por `get_last_successful_command()` e o replay é logado com o comando
real, não com a palavra `repetir`.

**Segurança desta etapa:**
- Apps resolvidos pelo índice liberam **somente o seu basename** na allowlist,
  via cópia da política feita dentro do dispatcher. `workflow run` continua com a
  allowlist original: um YAML com `params.indexed` não ganha nada.
- `.lnk` é aberto por `os.startfile` sobre um **caminho fixo** (sem string de
  comando, sem interpolação de argv) — não é `shell=True`.
- `raw_command` fica em texto claro no SQLite local porque `repetir` precisa
  reexecutá-lo. O terminal nunca mostra o payload de `digitar`: `redact_command`
  mascara em `do`, `historico` e no rótulo das ações. `gui_type` continua sem
  logar o texto.

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
