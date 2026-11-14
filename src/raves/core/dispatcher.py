"""Interpretador deterministico de pedidos em linguagem natural (pt-BR).

Nao ha LLM: cada frase e mapeada por regex para uma acao do engine. A execucao
passa pelo MESMO gate de seguranca do ``workflow run`` (allowlists, blacklist,
dry-run, auditoria, fail-closed). ``commands/workflow.py`` delega para
``execute_step`` deste modulo para nao duplicar a logica sensivel.

Etapa 1 de Blindagem: indice SQLite de apps, resolucao de nomes, memoria de
comandos (``repetir`` / ``historico``) e registro de toda execucao.
"""

from __future__ import annotations

import contextlib
import os
import re
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from raves.core import database
from raves.core.config import SecuritySettings, WorkflowStep, load_settings
from raves.core.diagnostics import capture_error_snapshot
from raves.core.learner import BehaviorLearner
from raves.core.lexicon import normalize_to_canonical
from raves.core.logger import audit, logger
from raves.core.security import RiskLevel, SecurityViolationError, classify_risk
from raves.core.session import session as _session
from raves.engine import gui, shell, uia_engine, vision, windows_api

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
    ~/.raves/crash_reports, conforme a Etapa 2 (RPA Nativo).
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

        elif action == "ocr_click":
            text = str(params.get("text", ""))
            if dry_run:
                outcome = StepOutcome(True, "simulado")
            else:
                ok, message = vision.click_text(text)
                outcome = StepOutcome(ok, message)

        elif action == "tocar_musica":
            if dry_run:
                outcome = StepOutcome(True, "simulado")
            else:
                ok, message = _tocar_musica(dry_run=dry_run, policy=policy)
                outcome = StepOutcome(ok, message)

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


_VERBS = r"abrir|fechar|focar|digitar|atalho|limpar|esperar|ps|clicar|tocar"

# Resolucoes conhecidas, consultadas ANTES do indice SQLite.
APP_ALIASES: dict[str, str] = {
    "calc": "calc.exe",
    "calculadora": "calc.exe",
    "bloco de notas": "notepad.exe",
    "notepad": "notepad.exe",
    "explorador": "explorer.exe",
    "explorer": "explorer.exe",
    "navegador": "chrome.exe",
    "browser": "chrome.exe",
    "editor": "code.exe",
    "planilha": "excel.exe",
    "texto": "notepad.exe",
    "pasta": "explorer.exe",
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
    impedir um pedido de executar. ``RAVES_SKIP_APP_INDEX`` desliga em testes.
    """
    global _index_checked
    if _index_checked or os.environ.get("RAVES_SKIP_APP_INDEX"):
        return 0
    _index_checked = True
    try:
        if database.count_apps() > 0:
            return 0
        # Import local: evita carregar winreg/varredura em `--help` e em testes.
        from raves.engine.app_indexer import scan_and_index_windows_apps

        return scan_and_index_windows_apps()
    except Exception as exc:  # indexing nunca pode ser fail-closed
        logger.warning(f"indexacao automatica ignorada: {exc}")
        audit(f"app_index auto failure={exc!r}")
        return 0


# Cortesia/preenchimento removidos ANTES do parser, preservando conteúdo entre aspas.
_FILLER_RE = re.compile(
    r"\b(por\s+favor|pra\s+mim|pode|consegue|agora|ei\s+rob[oô]|"
    r"por\s+gentileza|obrigado|obrigada|me\s+ajuda)\b,?",
    re.IGNORECASE,
)


def _normalize_instruction(text: str) -> str:
    """Remove cortesia/preenchimento sem alterar argumentos entre aspas."""
    if not text:
        return text
    parts = re.split(r"(\"[^\"]*\"|\'[^\']*\')", text)
    cleaned: list[str] = []
    for index, part in enumerate(parts):
        if index % 2 == 1:
            cleaned.append(part)
        else:
            value = _FILLER_RE.sub(" ", part)
            value = re.sub(r"\s+", " ", value).strip()
            cleaned.append(value)
    return " ".join(part for part in cleaned if part).strip()


_ARTICLES = {"o", "a", "os", "as", "um", "uma", "uns", "umas", "de", "do", "da", "the"}


def _strip_articles(text: str) -> str:
    tokens = text.split()
    while tokens and tokens[0].lower() in _ARTICLES:
        tokens.pop(0)
    return " ".join(tokens)


def _resolve_app_name(raw: str) -> str:
    """APP_ALIASES -> ``database.find_app`` -> raw puro (sem acrescentar .exe).

    Artigos iniciais ('o', 'a', 'um'...) sao descartados: 'abrir o chrome' e
    'abrir chrome' resolvem para o mesmo alvo.
    """
    cleaned = raw.strip().strip("\"'").strip()
    if not cleaned:
        raise ValueError("nome do aplicativo vazio")
    key = _strip_articles(cleaned).lower()
    if not key:
        key = cleaned.lower()
    if key in APP_ALIASES:
        return APP_ALIASES[key]
    found = database.find_app(key)
    if found:
        return found
    # Tenta tambem a forma original (sem strip) como fallback.
    if cleaned.lower() in APP_ALIASES:
        return APP_ALIASES[cleaned.lower()]
    found = database.find_app(cleaned)
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

    # Anafóricos: 'fecha ele' / 'fechar isso' / 'fechar janela' -> último app alvo.
    if text.lower() in {"fecha ele", "fechar isso", "fechar janela", "fechar ela"}:
        target = _session.last_target_app
        if not target:
            raise ValueError("nenhum aplicativo recente para fechar (abra um primeiro)")
        names = list(_PROCESS_ALIASES.get(target.lower(), (target,)))
        return [
            CommandSpec(
                f"fechar {target}",
                WorkflowStep(name="fechar", action="kill_process", params={"name": names}),
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

    if re.fullmatch(r"tocar\s+m[uú]sica", text, re.IGNORECASE):
        return [
            CommandSpec(
                "tocar musica",
                WorkflowStep(name="tocar musica", action="tocar_musica", params={}),
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
        window = _session.last_window_title or ""
        specs: list[CommandSpec] = []
        if window:
            specs.append(
                CommandSpec(
                    f"focar '{window}'",
                    WorkflowStep(name="focar", action="focus_window", params={"title": window}),
                )
            )
        specs.append(
            CommandSpec(
                f"clicar '{control}'" + (f" em '{window}'" if window else " (janela ativa)"),
                WorkflowStep(
                    name="uia_click",
                    action="uia_click",
                    params={"window": window, "control": control},
                ),
            )
        )
        return specs

    match = re.fullmatch(r"clicar\s+no\s+texto\s+(.+)", text, _FLAGS)
    if match:
        target = match.group(1).strip()
        return [
            CommandSpec(
                f"clicar no texto '{target}'",
                WorkflowStep(name="ocr_click", action="ocr_click", params={"text": target}),
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
        specs: list[CommandSpec] = []
        # Contexto de sessão: se houver janela alvo recente, foca antes de digitar.
        if _session.last_window_title:
            specs.append(
                CommandSpec(
                    f"focar '{_session.last_window_title}'",
                    WorkflowStep(
                        name="focar",
                        action="focus_window",
                        params={"title": _session.last_window_title},
                    ),
                )
            )
        specs.append(
            CommandSpec(
                f"digitar texto ({len(payload)} caractere(s))",
                WorkflowStep(name="digitar", action="gui_type", params={"text": payload}),
            )
        )
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


# Mapeamento best-effort de executável -> título de janela (pt-BR).
_APP_WINDOW_TITLES: dict[str, str] = {
    "notepad.exe": "Bloco de Notas",
    "calc.exe": "Calculadora",
    "chrome.exe": "Chrome",
    "msedge.exe": "Edge",
    "firefox.exe": "Firefox",
    "code.exe": "Visual Studio Code",
    "explorer.exe": "Explorador de Arquivos",
}


def parse_instruction(instruction: str) -> list[CommandSpec]:
    """Converte um pedido (possivelmente encadeado com ' e ') em passos.

    Resolve anáforas ('fecha ele', 'fechar isso') usando um contexto local que
    acompanha os passos já gerados nesta mesma instrução — assim
    'abrir notepad e digitar teste e fechar ele' funciona numa única chamada.
    """
    if not instruction or not instruction.strip():
        raise ValueError("pedido vazio")
    parts = [part.strip() for part in _CHAIN_RE.split(instruction.strip())]
    specs: list[CommandSpec] = []
    # Contexto local que acompanha a cadeia (independente do singleton global).
    local_target: str | None = _session.last_target_app
    local_window: str | None = _session.last_window_title
    for part in parts:
        if not part:
            continue
        # Override temporário do singleton para resolver anáforas neste segmento.
        saved_target = _session.last_target_app
        saved_window = _session.last_window_title
        _session.last_target_app = local_target
        _session.last_window_title = local_window
        try:
            seg_specs = _parse_segment(part)
        finally:
            _session.last_target_app = saved_target
            _session.last_window_title = saved_window
        specs.extend(seg_specs)
        # Atualiza o contexto local com base nos passos gerados.
        for spec in seg_specs:
            if spec.step.action == "launch_app":
                target = str(spec.step.params.get("target", ""))
                local_target = target
                local_window = _APP_WINDOW_TITLES.get(
                    target.lower(), Path(target).stem if target else local_window
                )
            elif spec.step.action == "focus_window":
                local_window = str(spec.step.params.get("title", "")) or local_window
    # Best-effort: reflete o último alvo no singleton para chamadas futuras.
    if local_target:
        _session.last_target_app = local_target
    if local_window:
        _session.last_window_title = local_window
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


def _run_specs(
    specs: list[CommandSpec],
    *,
    apply: bool,
    policy: SecuritySettings,
    confirm_fn: Any = None,
    auto_yes: bool = False,
) -> list[DispatchResult]:
    active = _policy_for(specs, policy)
    dry_run = not apply
    results: list[DispatchResult] = []
    for spec in specs:
        risk = classify_risk(spec.step.action, spec.step.params)
        if (not dry_run) and risk in (RiskLevel.YELLOW, RiskLevel.RED) and not auto_yes:
            if confirm_fn is not None:
                prompt = f"Confirmar: {spec.label} ({risk.value})?"
                try:
                    approved = bool(confirm_fn(prompt))
                except Exception:
                    approved = False
                if not approved:
                    results.append(
                        DispatchResult(spec.label, False, "cancelado pelo usuário", blocked=True)
                    )
                    break
            elif risk == RiskLevel.RED:
                results.append(
                    DispatchResult(
                        spec.label,
                        False,
                        "ação RED requer confirmação (--yes ou shell interativo)",
                        blocked=True,
                    )
                )
                break
        outcome = execute_step(spec.step, policy=active, dry_run=dry_run)
        results.append(DispatchResult(spec.label, outcome.ok, outcome.message, outcome.blocked))
        # Atualiza contexto de sessão em ações bem-sucedidas (anáforas).
        if outcome.ok and not outcome.blocked:
            if spec.step.action == "launch_app":
                _session.update_target(str(spec.step.params.get("target")))
            elif spec.step.action == "focus_window":
                _session.update_window(str(spec.step.params.get("title")))
            elif spec.step.action in {"uia_click", "ocr_click"}:
                window = spec.step.params.get("window")
                if window:
                    _session.update_window(str(window))
            elif spec.step.action == "gui_type":
                _session.set_entity("last_text", str(spec.step.params.get("text", ""))[:80])
        # Foco que falha não aborta a cadeia (ex.: anáfora 'digitar X' após 'abrir app').
        if outcome.blocked or (not outcome.ok and spec.step.action != "focus_window"):
            break
    return results


def _execute_instruction(
    raw: str,
    *,
    apply: bool,
    policy: SecuritySettings,
    confirm_fn: Any = None,
    auto_yes: bool = False,
) -> list[DispatchResult]:
    try:
        specs = parse_instruction(raw)
    except ValueError as exc:
        return [DispatchResult(raw, False, str(exc))]
    return _run_specs(specs, apply=apply, policy=policy, confirm_fn=confirm_fn, auto_yes=auto_yes)


def _tocar_musica(*, dry_run: bool, policy: SecuritySettings) -> tuple[bool, str]:
    """Abre o player/navegador preferido e, se houver estilo favorito, busca no YouTube."""
    import shutil
    from pathlib import Path

    profile = database.get_interest_profile()
    music = [item for item in profile if item["category"] == "musica"]
    favorite = music[0]["keyword"] if music else None

    player: str | None = None
    for candidate in ("spotify", "vlc", "wmplayer", "groove music", "chrome", "edge", "firefox"):
        found = database.find_app(candidate)
        if found:
            player = found
            break
    if player is None:
        player = shutil.which("explorer.exe")

    if not player:
        return False, "Nenhum player indexado. Rode 'raves apps sync'."

    args: list[str] | None = None
    if favorite and any(token in player.lower() for token in ("chrome", "edge", "firefox")):
        args = [f"https://www.youtube.com/results?search_query={favorite}+music"]

    active = policy
    if isinstance(policy, SecuritySettings):
        active = policy.model_copy(
            update={"allowed_apps": sorted({*policy.allowed_apps, Path(player).name.lower()})}
        )

    ok = windows_api.launch_app(player, args, dry_run=dry_run, policy=active)
    if not ok:
        return False, "Falha ao abrir o player"
    if favorite:
        return True, f"Tocando {favorite} em {Path(player).name}"
    return True, f"Player aberto: {Path(player).name}"


def _handle_preparar_ambiente(policy: SecuritySettings | None = None) -> list[DispatchResult]:
    """Executa a rotina de maior confiança para o hour_bucket atual."""
    from datetime import datetime

    current_bucket = database.hour_bucket_for(datetime.now().astimezone().hour)
    routines = database.get_routines()
    candidates = [r for r in routines if r["trigger_context"].endswith(f"bucket={current_bucket}")]
    if not candidates:
        candidates = routines
    if not candidates:
        return [
            DispatchResult(
                "preparar ambiente",
                True,
                "Nenhuma rotina aprendida ainda. Use o RAVES por alguns dias.",
            )
        ]
    best = max(candidates, key=lambda item: item["confidence"])
    launched: list[str] = []
    for action in best["suggested_actions"]:
        name = action.strip().lower()
        if name.endswith(".exe") or "." not in name:
            target = name if name.endswith(".exe") else f"{name}.exe"
            try:
                active = policy if policy is not None else load_settings().security
                if isinstance(active, SecuritySettings):
                    active = active.model_copy(
                        update={"allowed_apps": sorted({*active.allowed_apps, target.lower()})}
                    )
                windows_api.launch_app(target, dry_run=False, policy=active)
                launched.append(target)
            except Exception:
                continue
    detail = ", ".join(launched) if launched else "nenhum app lançado"
    return [
        DispatchResult(
            "preparar ambiente",
            True,
            f"Rotina '{best['trigger_context']}' ({best['confidence']:.0%}): {detail}",
        )
    ]


def _handle_memory(
    raw: str,
    *,
    apply: bool,
    policy: SecuritySettings,
    confirm_fn: Any = None,
    auto_yes: bool = False,
) -> list[DispatchResult]:
    lowered = raw.strip().lower()

    if any(lowered.startswith(prefix) for prefix in database.REPEAT_PREFIXES):
        last = database.get_last_successful_command()
        if not last or database.is_memory_command(last):
            result = [DispatchResult("repetir", False, "Nenhum comando anterior para repetir")]
            _log(raw, result)
            return result
        replay = _execute_instruction(
            last, apply=apply, policy=policy, confirm_fn=confirm_fn, auto_yes=auto_yes
        )
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


def _execute_natural_command_impl(
    instruction: str,
    *,
    apply: bool = True,
    policy: SecuritySettings | None = None,
    confirm_fn: Any = None,
    auto_yes: bool = False,
) -> list[DispatchResult]:
    """Interpreta e executa o pedido. Fail-closed: para no primeiro erro/bloqueio.

    ``apply=False`` simula (dry-run). Erros de parsing nao levantam excecao:
    retornam um ``DispatchResult`` com ``ok=False`` para a CLI renderizar.
    Comandos de memoria (``repetir``, ``historico``) valem sozinhos, nao em cadeia.
    """
    ensure_app_index()
    raw = _normalize_instruction(instruction.strip())
    # Lexico rapido: multiplica cobertura de vocabulario (O(1)).
    canonical = normalize_to_canonical(raw)
    if canonical and canonical != raw:
        raw = canonical
    # Cache semantico: frase ja aprendida -> execucao instantanea.
    learned = database.lookup_learned_phrase(raw)
    if learned:
        raw = learned
    active = policy if policy is not None else load_settings().security

    # Insight primeiro: esses prefixos tambem estao em MEMORY_PREFIXES (anti-loop),
    # mas precisam cair no learner, nao no repetir/historico.
    lowered = raw.strip().lower()

    if lowered in {"ler tela", "o que esta escrito na tela", "o que está escrito na tela"}:
        text = vision.read_screen_text()
        summary = text.strip()[:500] or "(nenhum texto detectado)"
        result = [DispatchResult("ler tela", True, summary)]
        _log(raw, result)
        return result

    # Hardware / midia / print
    if lowered in {"mutar", "desmutar", "mute", "unmute"}:
        from raves.engine import hardware

        result = [DispatchResult("mute", True, hardware.toggle_mute())]
        _log(raw, result)
        return result
    if lowered in {"aumentar volume", "volume mais", "volume up"}:
        from raves.engine import hardware

        result = [DispatchResult("volume", True, hardware.change_volume(10))]
        _log(raw, result)
        return result
    if lowered in {"diminuir volume", "volume menos", "volume down"}:
        from raves.engine import hardware

        result = [DispatchResult("volume", True, hardware.change_volume(-10))]
        _log(raw, result)
        return result
    if lowered in {"pausar musica", "pausar música", "play pause", "play/pause"}:
        from raves.engine import hardware

        result = [DispatchResult("midia", True, hardware.media_control("play_pause"))]
        _log(raw, result)
        return result
    if lowered in {"proxima musica", "próxima música", "next track", "proxima"}:
        from raves.engine import hardware

        result = [DispatchResult("midia", True, hardware.media_control("next"))]
        _log(raw, result)
        return result
    if lowered in {"musica anterior", "música anterior", "prev track", "anterior"}:
        from raves.engine import hardware

        result = [DispatchResult("midia", True, hardware.media_control("prev"))]
        _log(raw, result)
        return result
    if lowered in {"tirar print", "capturar tela", "screenshot"}:
        from raves.engine import hardware

        path = hardware.take_screenshot(save_to_desktop=True)
        result = [DispatchResult("print", True, f"Screenshot salvo em {path}")]
        _log(raw, result)
        return result

    # Leitura de documento
    if lowered.startswith("ler arquivo ") or lowered.startswith("resumir arquivo "):
        summarize = lowered.startswith("resumir arquivo ")
        file_path = (
            raw[len("resumir arquivo ") if summarize else len("ler arquivo ") :]
            .strip()
            .strip("\"'")
        )
        from raves.engine import doc_reader

        if summarize:
            text = doc_reader.summarize_document(file_path)
        else:
            text = doc_reader.extract_document_text(file_path)
        result = [DispatchResult("documento", True, text[:1000])]
        _log(raw, result)
        return result

    # Lembrete
    import re as _re

    reminder_match = _re.match(
        r"(?:me avisa em|lembrete em)\s+(\d+)\s+(minutos?|segundos?|horas?)\s+para\s+(.+)",
        raw,
        _re.IGNORECASE,
    )
    if reminder_match:
        amount = int(reminder_match.group(1))
        unit = reminder_match.group(2).lower()
        message = reminder_match.group(3).strip()
        if unit.startswith("min"):
            delay = amount * 60
        elif unit.startswith("hora"):
            delay = amount * 3600
        else:
            delay = amount
        from raves.core import reminders

        text = reminders.schedule_reminder(delay, message)
        result = [DispatchResult("lembrete", True, text)]
        _log(raw, result)
        return result

    # Volume com porcentagem
    volume_match = _re.match(r"volume\s+em\s+(\d+)\s*%?", raw, _re.IGNORECASE)
    if volume_match:
        from raves.engine import hardware

        result = [DispatchResult("volume", True, hardware.set_volume(int(volume_match.group(1))))]
        _log(raw, result)
        return result

    if lowered in {"tocar musica", "bota uma musica", "colocar minha musica", "tocar música"}:
        ok, message = _tocar_musica(dry_run=not apply, policy=active)
        result = [DispatchResult("tocar musica", ok, message)]
        _log(raw, result)
        return result

    if lowered in {"preparar meu ambiente", "modo trabalho", "preparar ambiente"}:
        result = _handle_preparar_ambiente(policy=active)
        _log(raw, result)
        return result

    if database.is_insight_command(raw):
        return _handle_insights(raw)
    if any(raw.lower().startswith(p) for p in database.VOICE_TRAIN_PREFIXES):
        return _handle_voice_training(raw)
    if database.is_memory_command(raw):
        return _handle_memory(
            raw, apply=apply, policy=active, confirm_fn=confirm_fn, auto_yes=auto_yes
        )

    # 1) Parser determinístico (1 ms).
    try:
        specs = parse_instruction(raw)
    except ValueError:
        specs = None

    if specs is not None:
        results = _run_specs(
            specs, apply=apply, policy=active, confirm_fn=confirm_fn, auto_yes=auto_yes
        )
        _log(raw, results)
        return results

    # 2) Cascata: cérebro híbrido local (Ollama) — só se disponível.
    try:
        from raves.ai.local_brain import LocalBrain

        brain = LocalBrain()
        if brain.is_available():
            reply = brain.ask(raw)
            action = reply.get("action")
            if action:
                results = _execute_instruction(
                    str(action),
                    apply=apply,
                    policy=active,
                    confirm_fn=confirm_fn,
                    auto_yes=auto_yes,
                )
                # Aprendizado de frase: salva o par (frase_usuario, comando) para
                # execucao instantanea nas proximas vezes (cache semantico).
                if results and all(item.ok and not item.blocked for item in results):
                    with contextlib.suppress(Exception):
                        database.save_learned_phrase(raw, str(action))
                _log(raw, results)
                return results
            text = str(reply.get("text", "")).strip()
            if text:
                result = [DispatchResult(raw, True, text)]
                _log(raw, result)
                return result
    except Exception as exc:
        logger.debug(f"local_brain: indisponível ({exc})")

    # 3) Fallback amigável offline.
    result = [
        DispatchResult(
            raw,
            False,
            "Comando não reconhecido. Tente: abrir/fechar/focar/digitar/atalho/limpar temp/"
            "esperar/ps/repetir/historico/sugestoes/meu perfil/ler tela/clicar no texto. "
            "(Ollama offline — instale em https://ollama.com para perguntas abertas.)",
        )
    ]
    _log(raw, result)
    return result


def execute_natural_command(
    instruction: str,
    *,
    apply: bool = True,
    policy: SecuritySettings | None = None,
    confirm_fn: Any = None,
    auto_yes: bool = False,
) -> list[DispatchResult]:
    """Wrapper publico: executa + registra turnos de conversa + cache semantico."""
    raw_original = (instruction or "").strip()
    results = _execute_natural_command_impl(
        instruction, apply=apply, policy=policy, confirm_fn=confirm_fn, auto_yes=auto_yes
    )
    # Memoria conversacional (Etapa 10): registra user + assistant.
    try:
        database.append_turn("user", raw_original, None)
        if results:
            summary = " | ".join(
                ("OK" if item.ok and not item.blocked else "X")
                + " "
                + item.label
                + ": "
                + item.message
                for item in results
            )[:500]
            database.append_turn("assistant", summary, None)
    except Exception:
        pass
    return results
