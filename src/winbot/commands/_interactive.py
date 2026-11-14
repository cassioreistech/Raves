"""Sessão interativa compartilhada por ``shell`` e ``voice listen``.

Mantém num único lugar: renderização dos resultados, gate de licença, bootstrap
do observador de contexto, saudação proativa e o loop de pedidos.
"""

from __future__ import annotations

import os

import typer
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.prompt import Prompt

from winbot.core.config import Settings
from winbot.core.dispatcher import DispatchResult, execute_natural_command
from winbot.core.learner import BehaviorLearner
from winbot.core.licensing import LicenseError, check_license_or_raise
from winbot.engine.observer import ContextObserver

console = Console()


def status_icons() -> tuple[str, str]:
    """✔/✘ em UTF-8; fallback ASCII em console cp1252 (ver PLAN.md §7)."""
    encoding = (getattr(console.file, "encoding", "") or "").lower().replace("-", "")
    return ("✔", "✘") if "utf" in encoding else ("OK", "X")


def render_results(results: list[DispatchResult]) -> None:
    ok_icon, bad_icon = status_icons()
    for item in results:
        good = item.ok and not item.blocked
        icon = ok_icon if good else bad_icon
        color = "green" if good else "red"
        prefix = "BLOQUEADO: " if item.blocked else ""
        console.print(
            f"  [{color}]{icon}[/{color}] [bold]{escape(item.label)}[/bold] "
            f"[dim]{escape(prefix + item.message)}[/dim]"
        )


def enforce_license(settings: Settings) -> None:
    """Mesmo gate comercial de ``workflow run``."""
    if not settings.licensing.enabled:
        return
    try:
        check_license_or_raise()
    except LicenseError as exc:
        console.print(f"[bold red]Licença:[/bold red] {escape(str(exc))}")
        raise typer.Exit(code=1) from exc


def start_observer() -> ContextObserver | None:
    """Liga a telemetria passiva. Retorna None se desligada por env."""
    if os.environ.get("WINBOT_OBSERVER_DISABLED"):
        return None
    observer = ContextObserver()
    observer.start_background_watch()
    console.print(
        "[dim]Observador de contexto ativo (dados só neste computador). "
        "WINBOT_OBSERVER_DISABLED=1 desliga · 'insights forget' apaga tudo.[/dim]"
    )
    return observer


def show_proactive_greeting() -> str | None:
    """Consolida padrões e exibe a sugestão, se houver (nunca executa nada)."""
    learner = BehaviorLearner()
    learner.analyze_patterns()
    greeting = learner.get_proactive_greeting()
    if greeting:
        console.print(Panel(escape(greeting), title="Sugestão", border_style="cyan"))
    return greeting


def interactive_loop(*, prompt: str, header: str, dry_run: bool, settings: Settings) -> None:
    """Loop de pedidos com observer + saudação na abertura e parada limpa."""
    enforce_license(settings)
    observer = start_observer()
    try:
        console.print(header)
        show_proactive_greeting()
        while True:
            try:
                pedido = Prompt.ask(prompt, console=console).strip()
            except (EOFError, KeyboardInterrupt):
                console.print()
                break
            if not pedido:
                continue
            if pedido.casefold() in {"sair", "exit", "quit"}:
                break
            results = execute_natural_command(pedido, apply=not dry_run, policy=settings.security)
            render_results(results)
    finally:
        if observer is not None:
            observer.stop()
    console.print("[dim]Até logo.[/dim]")
