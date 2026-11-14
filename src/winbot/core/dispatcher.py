"""Interpretador deterministico de pedidos em linguagem natural (pt-BR).

Nao ha LLM: cada frase e mapeada por regex para uma acao do engine. A execucao
passa pelo MESMO gate de seguranca do ``workflow run`` (allowlists, blacklist,
dry-run, auditoria, fail-closed). ``commands/workflow.py`` delega para
``execute_step`` deste modulo para nao duplicar a logica sensivel.
"""

from __future__ import annotations

import re
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from winbot.core.config import SecuritySettings, WorkflowStep, load_settings
from winbot.core.logger import audit
from winbot.core.security import SecurityViolationError
from winbot.engine import gui, shell, windows_api

__all__ = [
    "CommandSpec",
    "DispatchResult",
    "StepOutcome",
    "execute_natural_command",
    "execute_step",
    "parse_instruction",
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
    """Executa uma acao validada. Violacao de seguranca => blocked=True (fail-closed)."""
    action, params = step.action, step.params
    try:
        if action == "powershell":
            res = shell.run_powershell(
                str(params.get("command", "")),
                timeout=int(params.get("timeout", 30)),
                policy=policy,
                dry_run=dry_run,
            )
            if res.simulated:
                return StepOutcome(True, "simulado")
            message = res.stdout.strip() if res.success else res.stderr.strip()
            return StepOutcome(res.success, message or "sem saida")

        if action == "launch_app":
            ok = windows_api.launch_app(
                str(params.get("target", "")),
                params.get("args"),
                dry_run=dry_run,
                policy=policy,
            )
            return StepOutcome(ok, f"App iniciado: {params.get('target')}" if ok else "Falha")

        if action == "kill_process":
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
            return StepOutcome(True, f"{count} instancia(s) {suffix}")

        if action == "focus_window":
            ok = windows_api.focus_window(str(params.get("title", "")), dry_run=dry_run)
            return StepOutcome(ok, "Janela focada" if ok else "Janela nao encontrada")

        if action == "gui_click":
            detail = gui.click_at(int(params["x"]), int(params["y"]), dry_run=dry_run)
            return StepOutcome(True, detail)

        if action == "gui_click_image":
            detail = gui.click_image(
                str(params["image"]),
                dry_run=dry_run,
                timeout=float(params.get("timeout", 10)),
            )
            return StepOutcome(detail != "imagem nao encontrada na tela", detail)

        if action == "gui_type":
            detail = gui.type_text_safe(str(params["text"]), dry_run=dry_run)
            return StepOutcome(True, detail)

        if action == "gui_hotkey":
            detail = gui.hotkey([str(key) for key in params["keys"]], dry_run=dry_run)
            return StepOutcome(True, detail)

        if action == "clean_temp":
            return StepOutcome(True, _clean_temp(dry_run=dry_run))

        if action == "wait":
            seconds = float(params.get("seconds", 1))
            if not dry_run:
                time.sleep(seconds)
            return StepOutcome(
                True, f"Aguardaria {seconds}s" if dry_run else f"Aguardou {seconds}s"
            )

        return StepOutcome(False, f"Acao nao suportada: {action}")
    except SecurityViolationError as exc:
        return StepOutcome(False, str(exc), blocked=True)
    except OSError as exc:
        return StepOutcome(False, str(exc))


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


_VERBS = r"abrir|fechar|focar|digitar|atalho|limpar|esperar|ps"

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


def _normalize_app(raw: str) -> str:
    """'calc' -> 'calc.exe' (allowlist e psutil usam o nome com extensao)."""
    name = raw.strip().strip("\"'").strip()
    if not name:
        raise ValueError("nome do aplicativo vazio")
    return name if name.lower().endswith(".exe") else f"{name}.exe"


def _parse_keys(raw: str) -> list[str]:
    keys = [key.strip().lower() for key in re.split(r"[\s+]+", raw.strip()) if key.strip()]
    if not keys:
        raise ValueError("atalho exige as teclas, ex.: 'atalho ctrl+c'")
    return keys


def _parse_segment(segment: str) -> list[CommandSpec]:
    text = segment.strip()

    match = re.fullmatch(r"abrir\s+(.+)", text, _FLAGS)
    if match:
        app = _normalize_app(match.group(1))
        return [
            CommandSpec(
                f"abrir {app}",
                WorkflowStep(name="abrir", action="launch_app", params={"target": app}),
            )
        ]

    match = re.fullmatch(r"fechar\s+(.+)", text, _FLAGS)
    if match:
        app = _normalize_app(match.group(1))
        names = list(_PROCESS_ALIASES.get(app.lower(), (app,)))
        return [
            CommandSpec(
                f"fechar {app}",
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

    match = re.fullmatch(r"digitar\s+(.+)", text, _FLAGS)
    if match:
        payload = match.group(1).strip()
        enter = re.search(r"\s+com\s+enter\s*$", payload, re.IGNORECASE)
        if enter:
            payload = payload[: enter.start()].strip()
        if not payload:
            raise ValueError("digitar exige um texto")
        # O texto NAO entra no rotulo nem em log: pode ser uma senha.
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


def execute_natural_command(
    instruction: str,
    *,
    apply: bool = True,
    policy: SecuritySettings | None = None,
) -> list[DispatchResult]:
    """Interpreta e executa o pedido. Fail-closed: para no primeiro erro/bloqueio.

    ``apply=False`` simula (dry-run). Erros de parsing nao levantam excecao:
    retornam um ``DispatchResult`` com ``ok=False`` para a CLI renderizar.
    """
    try:
        specs = parse_instruction(instruction)
    except ValueError as exc:
        return [DispatchResult(instruction.strip(), False, str(exc))]

    active = policy if policy is not None else load_settings().security
    dry_run = not apply
    results: list[DispatchResult] = []
    for spec in specs:
        outcome = execute_step(spec.step, policy=active, dry_run=dry_run)
        results.append(DispatchResult(spec.label, outcome.ok, outcome.message, outcome.blocked))
        if outcome.blocked or not outcome.ok:
            break
    return results
