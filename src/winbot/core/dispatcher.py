"""Interpretador deterministico de pedidos em linguagem natural (pt-BR).

Nao ha LLM: cada frase e mapeada por regex para uma acao do engine. A execucao
passa pelo MESMO gate de seguranca do ``workflow run`` (allowlists, blacklist,
dry-run, auditoria, fail-closed). ``commands/workflow.py`` delega para
``execute_step`` deste modulo para nao duplicar a logica sensivel.

Etapa 1 de Blindagem: indice SQLite de apps, resolucao de nomes, memoria de
comandos (``repetir`` / ``historico``) e registro de toda execucao.
"""

from __future__ import annotations

import os
import re
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from winbot.core import database
from winbot.core.config import SecuritySettings, WorkflowStep, load_settings
from winbot.core.diagnostics import capture_error_snapshot
from winbot.core.learner import BehaviorLearner
from winbot.core.logger import audit, logger
from winbot.core.security import SecurityViolationError
from winbot.engine import gui, shell, uia_engine, windows_api

__all__ = [
    "APP_ALIASES",
    "CommandSpec",
    "DispatchResult",
    "StepOutcome",
    "ensure_app_index",
    "execute_natural_command",
    "execute_step",
    "parse_instruction",
    "redact_command",
]


# ---------------------------------------------------------------------------
# Execucao (fonte unica, compartilhada com workflow run)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StepOutcome:
    ok: bool
    message: str
    blocked: bool = False


def _clean_temp(*, dry_run: bool) -> str:
    """Limpa SOMENTE arquivos regulares diretamente em %TEMP%.

    Escopo deliberadamente estreito (decisao N3): sem recursao, sem diretorios,
    sem symlinks/junctions, ignora arquivos em uso. Nunca toca em %TEMP%\\onefile_*
    (usado pelo binario Nuitka) pois sao diretorios.
    """
    base = Path(tempfile.gettempdir())
    candidates = [path for path in base.iterdir() if path.is_file() and not path.is_symlink()]
    audit(f"clean_temp dir={base!r} candidates={len(candidates)} dry_run={dry_run}")
    if dry_run:
        return f"{len(candidates)} arquivo(s) seriam removidos de {base}"

    removed = 0
    for path in candidates:
        try:
            path.unlink()
            removed += 1
        except OSError:
            continue  # arquivo em uso / sem permissao: ignora, nao aborta
    return f"{removed}/{len(candidates)} arquivo(s) removido(s) de {base}"


def execute_step(step: WorkflowStep, *, policy: SecuritySettings, dry_run: bool) -> StepOutcome:
    """Executa uma acao validada. Violacao de seguranca => blocked=True (fail-closed).

    Toda falha (excecao ou resultado False) gera um snapshot de diagnostico em
    ~/.winbot/crash_reports, conforme a Etapa 2 (RPA Nativo).
    """
    action, params = step.action, step.params
    outcome: StepOutcome | None = None
    try:
        if action == "powershell":
            res = shell.run_powershell(
                str(params.get("command", "")),
                timeout=int(params.get("timeout", 30)),
                policy=policy,
                dry_run=dry_run,
            )
            if res.simulated:
                outcome = StepOutcome(True, "simulado")
            else:
                message = res.stdout.strip() if res.success else res.stderr.strip()
                outcome = StepOutcome(res.success, message or "sem saida")

        elif action == "launch_app":
            ok = windows_api.launch_app(
                str(params.get("target", "")),
                params.get("args"),
                dry_run=dry_run,
                policy=policy,
            )
            outcome = StepOutcome(ok, f"App iniciado: {params.get('target')}" if ok else "Falha")

        elif action == "kill_process":
            raw_names = params.get("name", "")
            names = (
                [str(name) for name in raw_names]
                if isinstance(raw_names, list)
                else [str(raw_names)]
            )
            count = sum(
                windows_api.kill_process_by_name(name, dry_run=dry_run, policy=policy)
                for name in names
            )
            suffix = "seriam encerradas" if dry_run else "encerrada(s)"
            outcome = StepOutcome(True, f"{count} instancia(s) {suffix}")

        elif action == "focus_window":
            ok = windows_api.focus_window(str(params.get("title", "")), dry_run=dry_run)
            outcome = StepOutcome(ok, "Janela focada" if ok else "Janela nao encontrada")

        elif action == "gui_click":
            detail = gui.click_at(int(params["x"]), int(params["y"]), dry_run=dry_run)
            outcome = StepOutcome(True, detail)

        elif action == "gui_click_image":
            detail = gui.click_image(
                str(params["image"]),
                dry_run=dry_run,
                timeout=float(params.get("timeout", 10)),
            )
            outcome = StepOutcome(detail != "imagem nao encontrada na tela", detail)

        elif action == "gui_type":
            detail = gui.type_text_safe(str(params["text"]), dry_run=dry_run)
            outcome = StepOutcome(True, detail)

        elif action == "gui_hotkey":
            detail = gui.hotkey([str(key) for key in params["keys"]], dry_run=dry_run)
            outcome = StepOutcome(True, detail)

        elif action == "clean_temp":
            outcome = StepOutcome(True, _clean_temp(dry_run=dry_run))

        elif action == "wait":
            seconds = float(params.get("seconds", 1))
            if not dry_run:
                time.sleep(seconds)
            outcome = StepOutcome(
                True, f"Aguardaria {seconds}s" if dry_run else f"Aguardou {seconds}s"
            )

        elif action == "uia_click":
            if dry_run:
                outcome = StepOutcome(True, "simulado")
            else:
                window = str(params.get("window", "") or "")
                if not window:
                    window = uia_engine.foreground_window_title() or ""
                ok, message = uia_engine.click_control(
                    window,
                    str(params.get("control", "")),
                    params.get("control_type"),
                )
                outcome = StepOutcome(ok, message)

        elif action == "uia_fill":
            if dry_run:
                outcome = StepOutcome(True, "simulado")
            else:
                ok, message = uia_engine.fill_field(
                    str(params.get("window", "")),
                    str(params.get("control", "")),
                    str(params.get("text", "")),
                    bool(params.get("press_enter", False)),
                )
                outcome = StepOutcome(ok, message)

        elif action == "wait_window":
            title = str(params.get("title", ""))
            timeout = int(params.get("timeout", 15))
            if dry_run:
                outcome = StepOutcome(True, f"aguardaria janela '{title}'")
            else:
                ok = uia_engine.wait_for_window(title, timeout)
                outcome = StepOutcome(
                    ok, "Janela pronta" if ok else "Janela nao encontrada no timeout"
                )

        else:
            outcome = StepOutcome(False, f"Acao nao suportada: {action}")

    except SecurityViolationError as exc:
        capture_error_snapshot(step.name, str(exc))
        return StepOutcome(False, str(exc), blocked=True)
    except Exception as exc:
        capture_error_snapshot(step.name, str(exc))
        return StepOutcome(False, str(exc))

    assert outcome is not None
    if not outcome.ok:
        capture_error_snapshot(step.name, outcome.message)
    return outcome


# ---------------------------------------------------------------------------
# Parser deterministico
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CommandSpec:
    """Um passo executavel e o rotulo que sera mostrado ao operador."""

    label: str
    step: WorkflowStep


@dataclass(frozen=True)
class DispatchResult:
    label: str
    ok: bool
    message: str
    blocked: bool = False


_VERBS = r"abrir|fechar|focar|digitar|atalho|limpar|esperar|ps|clicar"

# Resolucoes conhecidas, consultadas ANTES do indice SQLite.
APP_ALIASES: dict[str, str] = {
    "calc": "calc.exe",
    "calculadora": "calc.exe",
    "bloco de notas": "notepad.exe",
    "notepad": "notepad.exe",
    "explorador": "explorer.exe",
    "explorer": "explorer.exe",
}

# Stubs do Windows que apenas iniciam outro processo. Sem estes aliases,
# "fechar calc" encerra 0 processos: o real e Calculator.exe (Win10) ou
# CalculatorApp.exe (Win11). Nomes EXPLICITOS, nunca substring: ampliar o
# casamento aumentaria a superficie de kill. Cada nome passa pela denylist.
_PROCESS_ALIASES: dict[str, tuple[str, ...]] = {
    "calc.exe": ("calc.exe", "calculator.exe", "calculatorapp.exe"),
}

# So quebra a cadeia quando depois do " e " vem um verbo conhecido. Assim
# "digitar Joao e Maria" continua um unico texto em vez de virar dois comandos.
_CHAIN_RE = re.compile(r"\s+e\s+(?=(?:" + _VERBS + r")\b)", re.IGNORECASE)
_FLAGS = re.IGNORECASE | re.DOTALL

# Guarda de "uma vez por processo" para a indexacao automatica.
_index_checked = False


def ensure_app_index() -> int:
    """Indexa automaticamente UMA vez, e so se ``installed_apps`` estiver vazia.

    Indexacao e oportunista: qualquer falha e registrada e ignorada, nunca pode
    impedir um pedido de executar. ``WINBOT_SKIP_APP_INDEX`` desliga em testes.
    """
    global _index_checked
    if _index_checked or os.environ.get("WINBOT_SKIP_APP_INDEX"):
        return 0
    _index_checked = True
    try:
        if database.count_apps() > 0:
            return 0
        # Import local: evita carregar winreg/varredura em `--help` e em testes.
        from winbot.engine.app_indexer import scan_and_index_windows_apps

        return scan_and_index_windows_apps()
    except Exception as exc:  # indexing nunca pode ser fail-closed
        logger.warning(f"indexacao automatica ignorada: {exc}")
        audit(f"app_index auto failure={exc!r}")
        return 0


def _resolve_app_name(raw: str) -> str:
    """APP_ALIASES -> ``database.find_app`` -> raw puro (sem acrescentar .exe)."""
    cleaned = raw.strip().strip("\"'").strip()
    if not cleaned:
        raise ValueError("nome do aplicativo vazio")
    key = cleaned.lower()
    if key in APP_ALIASES:
        return APP_ALIASES[key]
    found = database.find_app(key)
    if found:
        return found
    return cleaned


def _is_indexed_path(value: str) -> bool:
    """O indice devolve caminhos absolutos (.exe do registro ou .lnk do menu)."""
    return Path(value).is_absolute() or value.lower().endswith(".lnk")


def _parse_keys(raw: str) -> list[str]:
    keys = [key.strip().lower() for key in re.split(r"[\s+]+", raw.strip()) if key.strip()]
    if not keys:
        raise ValueError("atalho exige as teclas, ex.: 'atalho ctrl+c'")
    return keys


def _parse_segment(segment: str) -> list[CommandSpec]:
    text = segment.strip()

    match = re.fullmatch(r"abrir\s+(.+)", text, _FLAGS)
    if match:
        resolved = _resolve_app_name(match.group(1))
        indexed = _is_indexed_path(resolved)
        label_name = Path(resolved).name if indexed else resolved
        params: dict[str, object] = {"target": resolved}
        if indexed:
            # Marcador INTERNO: so execute_natural_command o consome para liberar
            # o basename na allowlist. Um YAML nunca consegue usar este atalho.
            params["indexed"] = True
        return [
            CommandSpec(
                f"abrir {label_name}",
                WorkflowStep(name="abrir", action="launch_app", params=params),
            )
        ]

    match = re.fullmatch(r"fechar\s+(.+)", text, _FLAGS)
    if match:
        resolved = _resolve_app_name(match.group(1))
        proc = Path(resolved).name.lower() if _is_indexed_path(resolved) else resolved.lower()
        if not proc.endswith(".exe"):
            proc = f"{proc}.exe"  # psutil compara pelo nome real do processo
        names = list(_PROCESS_ALIASES.get(proc, (proc,)))
        return [
            CommandSpec(
                f"fechar {proc}",
                WorkflowStep(name="fechar", action="kill_process", params={"name": names}),
            )
        ]

    match = re.fullmatch(r"focar\s+(.+)", text, _FLAGS)
    if match:
        title = match.group(1).strip()
        return [
            CommandSpec(
                f"focar '{title}'",
                WorkflowStep(name="focar", action="focus_window", params={"title": title}),
            )
        ]

    # UIA: "clicar em <controle> na janela <titulo>" ou "clicar no botao <controle>"
    # (usa a janela ativa quando o titulo nao e informado).
    match = re.fullmatch(r"clicar\s+em\s+(.+?)\s+na\s+janela\s+(.+)", text, _FLAGS)
    if match:
        control = match.group(1).strip()
        window = match.group(2).strip()
        return [
            CommandSpec(
                f"clicar '{control}' em '{window}'",
                WorkflowStep(
                    name="uia_click",
                    action="uia_click",
                    params={"window": window, "control": control},
                ),
            )
        ]

    match = re.fullmatch(r"clicar\s+no\s+bot[aã]o\s+(.+)", text, _FLAGS)
    if match:
        control = match.group(1).strip()
        return [
            CommandSpec(
                f"clicar '{control}' (janela ativa)",
                WorkflowStep(
                    name="uia_click",
                    action="uia_click",
                    params={"window": "", "control": control},
                ),
            )
        ]

    match = re.fullmatch(r"digitar\s+(.+)", text, _FLAGS)
    if match:
        payload = match.group(1).strip()
        enter = re.search(r"\s+com\s+enter\s*$", payload, re.IGNORECASE)
        if enter:
            payload = payload[: enter.start()].strip()
        if not payload:
            raise ValueError("digitar exige um texto")
        # O texto NAO entra no rotulo nem em result_message: pode ser uma senha.
        specs = [
            CommandSpec(
                f"digitar texto ({len(payload)} caractere(s))",
                WorkflowStep(name="digitar", action="gui_type", params={"text": payload}),
            )
        ]
        if enter:
            specs.append(
                CommandSpec(
                    "pressionar Enter",
                    WorkflowStep(name="enter", action="gui_hotkey", params={"keys": ["enter"]}),
                )
            )
        return specs

    match = re.fullmatch(r"atalho\s+(.+)", text, _FLAGS)
    if match:
        keys = _parse_keys(match.group(1))
        return [
            CommandSpec(
                f"atalho {'+'.join(keys)}",
                WorkflowStep(name="atalho", action="gui_hotkey", params={"keys": keys}),
            )
        ]

    if re.fullmatch(r"limpar\s+temp", text, re.IGNORECASE):
        return [
            CommandSpec(
                "limpar temp",
                WorkflowStep(name="limpar temp", action="clean_temp", params={}),
            )
        ]

    match = re.fullmatch(r"esperar\s+janela\s+(.+)", text, re.IGNORECASE)
    if match:
        title = match.group(1).strip()
        timeout = 15
        return [
            CommandSpec(
                f"esperar janela '{title}'",
                WorkflowStep(
                    name="wait_window",
                    action="wait_window",
                    params={"title": title, "timeout": timeout},
                ),
            )
        ]

    match = re.fullmatch(r"esperar\s+(\d+(?:\.\d+)?)\s*segundos?", text, re.IGNORECASE)
    if match:
        seconds = float(match.group(1))
        return [
            CommandSpec(
                f"esperar {seconds:g} segundo(s)",
                WorkflowStep(name="esperar", action="wait", params={"seconds": seconds}),
            )
        ]

    match = re.fullmatch(r"ps\s+(.+)", text, _FLAGS)
    if match:
        command = match.group(1).strip()
        return [
            CommandSpec(
                "ps (PowerShell)",
                WorkflowStep(name="ps", action="powershell", params={"command": command}),
            )
        ]

    raise ValueError(f"Comando nao reconhecido: '{text}'")


def parse_instruction(instruction: str) -> list[CommandSpec]:
    """Converte um pedido (possivelmente encadeado com ' e ') em passos."""
    if not instruction or not instruction.strip():
        raise ValueError("pedido vazio")
    parts = [part.strip() for part in _CHAIN_RE.split(instruction.strip())]
    specs: list[CommandSpec] = []
    for part in parts:
        if part:
            specs.extend(_parse_segment(part))
    return specs


def redact_command(raw: str) -> str:
    """Mascara o payload de ``digitar`` antes de EXIBIR o historico.

    ``raw_command`` continua integral no SQLite (necessario para ``repetir``),
    mas nunca aparece no terminal — pode conter senha.
    """
    parts = _CHAIN_RE.split(raw.strip())
    masked: list[str] = []
    for part in parts:
        segment = part.strip()
        match = re.fullmatch(r"(digitar\s+)(.+?)(\s+com\s+enter)?", segment, _FLAGS)
        if match:
            masked.append(
                f"{match.group(1)}texto ({len(match.group(2).strip())} caractere(s))"
                f"{match.group(3) or ''}"
            )
        else:
            masked.append(segment)
    return " e ".join(masked)


# ---------------------------------------------------------------------------
# Orquestracao + memoria
# ---------------------------------------------------------------------------


def _log(raw: str, results: list[DispatchResult]) -> None:
    """Registra toda execucao. Falha de gravacao nao derruba o pedido."""
    success = bool(results) and all(item.ok and not item.blocked for item in results)
    summary = " | ".join(
        f"{'OK' if item.ok and not item.blocked else 'X'} {item.label}: {item.message}"
        for item in results
    )
    try:
        database.log_command(raw, success, summary[:2000])
    except Exception as exc:  # disco cheio / permissao: nao e fail-closed
        logger.warning(f"historico nao gravado: {exc}")


def _policy_for(specs: list[CommandSpec], policy: SecuritySettings) -> SecuritySettings:
    """Libera SOMENTE os basenames resolvidos pelo indice nesta instrucao.

    Nao afeta ``workflow run``: a copia e feita aqui, dentro do dispatcher.
    Um YAML com ``params.indexed`` nao ganha nada, pois ``execute_step`` ignora
    essa chave — a allowlist continua sendo a politica original.
    """
    extra = {
        Path(str(spec.step.params["target"])).name.lower()
        for spec in specs
        if spec.step.action == "launch_app" and spec.step.params.get("indexed")
    }
    if not extra:
        return policy
    return policy.model_copy(update={"allowed_apps": sorted({*policy.allowed_apps, *extra})})


def _execute_instruction(
    raw: str, *, apply: bool, policy: SecuritySettings
) -> list[DispatchResult]:
    try:
        specs = parse_instruction(raw)
    except ValueError as exc:
        return [DispatchResult(raw, False, str(exc))]

    active = _policy_for(specs, policy)
    dry_run = not apply
    results: list[DispatchResult] = []
    for spec in specs:
        outcome = execute_step(spec.step, policy=active, dry_run=dry_run)
        results.append(DispatchResult(spec.label, outcome.ok, outcome.message, outcome.blocked))
        if outcome.blocked or not outcome.ok:
            break
    return results


def _handle_memory(raw: str, *, apply: bool, policy: SecuritySettings) -> list[DispatchResult]:
    lowered = raw.strip().lower()

    if any(lowered.startswith(prefix) for prefix in database.REPEAT_PREFIXES):
        last = database.get_last_successful_command()
        if not last or database.is_memory_command(last):
            result = [DispatchResult("repetir", False, "Nenhum comando anterior para repetir")]
            _log(raw, result)
            return result
        replay = _execute_instruction(last, apply=apply, policy=policy)
        # Loga o comando REAL, nao a palavra "repetir": o ultimo sucesso continua
        # sendo o mesmo e nao ha loop infinito.
        _log(last, replay)
        return [
            DispatchResult("repetir", True, f"Reexecutando: {redact_command(last)}"),
            *replay,
        ]

    history = database.get_recent_history(limit=5)
    if not history:
        result = [DispatchResult("historico", True, "Nenhum comando registrado ainda")]
        _log(raw, result)
        return result
    rows = []
    for item in history:
        detail = item["result_message"]
        if len(detail) > 90:
            detail = detail[:87] + "..."
        rows.append(
            DispatchResult(
                f"#{item['id']} {redact_command(item['raw_command'])}",
                True,
                f"{'OK' if item['success'] else 'FALHOU'} · {item['executed_at']} · {detail}",
            )
        )
    # Resumo curto: logar as proprias linhas criaria um historico recursivo.
    _log(raw, [DispatchResult("historico", True, f"{len(rows)} comando(s) exibido(s)")])
    return rows


def _handle_insights(raw: str) -> list[DispatchResult]:
    """'o que voce aprendeu' / 'me de uma dica' / 'sugestoes' / 'meu perfil'."""
    learner = BehaviorLearner()
    try:
        patterns = learner.analyze_patterns()
        tips = learner.get_recommendations()
    except Exception as exc:  # analise nunca pode derrubar um pedido
        result = [DispatchResult(raw, False, f"Falha ao analisar perfil: {exc}")]
        _log(raw, result)
        return result

    results = [
        DispatchResult("aprendizado", True, f"{patterns} padrão(ões) consolidado(s)"),
        *[DispatchResult(f"dica {index}", True, tip) for index, tip in enumerate(tips, start=1)],
    ]
    # Resumo curto: logar as dicas inteiras inflaria o command_history.
    _log(raw, [DispatchResult(raw, True, f"{patterns} padrões / {len(tips)} dicas")])
    return results


def _handle_voice_training(raw: str) -> list[DispatchResult]:
    """'quando eu disser X entenda Y' / 'aprender palavra X' / 'memorizar termo X'."""
    # "quando eu disser <heard> entenda <mapped>"
    match = re.match(
        r"quando\s+eu\s+disser\s+(.+?)\s+entenda\s+(.+)", raw.strip(), re.IGNORECASE | re.DOTALL
    )
    if match:
        heard = match.group(1).strip()
        mapped = match.group(2).strip()
        if database.save_speech_correction(heard, mapped):
            return [DispatchResult("voz", True, f"Aprendido: '{heard}' → '{mapped}'")]
        return [DispatchResult("voz", False, "Não foi possível salvar a correção")]

    # "aprender palavra <termo>" / "memorizar termo <termo>"
    match = re.match(
        r"(?:aprender\s+palavra|memorizar\s+termo)\s+(.+)", raw.strip(), re.IGNORECASE | re.DOTALL
    )
    if match:
        term = match.group(1).strip()
        if database.add_custom_vocab(term):
            return [DispatchResult("voz", True, f"Termo '{term}' memorizado para o Whisper")]
        return [DispatchResult("voz", False, f"'{term}' já estava no vocabulário")]

    return [DispatchResult("voz", False, f"Comando de treino não reconhecido: '{raw}'")]


def execute_natural_command(
    instruction: str,
    *,
    apply: bool = True,
    policy: SecuritySettings | None = None,
) -> list[DispatchResult]:
    """Interpreta e executa o pedido. Fail-closed: para no primeiro erro/bloqueio.

    ``apply=False`` simula (dry-run). Erros de parsing nao levantam excecao:
    retornam um ``DispatchResult`` com ``ok=False`` para a CLI renderizar.
    Comandos de memoria (``repetir``, ``historico``) valem sozinhos, nao em cadeia.
    """
    ensure_app_index()
    raw = instruction.strip()
    active = policy if policy is not None else load_settings().security

    # Insight primeiro: esses prefixos tambem estao em MEMORY_PREFIXES (anti-loop),
    # mas precisam cair no learner, nao no repetir/historico.
    if database.is_insight_command(raw):
        return _handle_insights(raw)
    if any(raw.lower().startswith(p) for p in database.VOICE_TRAIN_PREFIXES):
        return _handle_voice_training(raw)
    if database.is_memory_command(raw):
        return _handle_memory(raw, apply=apply, policy=active)

    results = _execute_instruction(raw, apply=apply, policy=active)
    _log(raw, results)
    return results
