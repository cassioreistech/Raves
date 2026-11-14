"""Orquestrador principal da CLI."""

from __future__ import annotations

import sys
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape
from rich.prompt import Prompt
from rich.table import Table

from winbot import __version__
from winbot.commands import (
    ai_cmd,
    apps,
    flow,
    insights,
    rpa_tools,
    schedule,
    system,
    tray,
    triggers_cmd,
    voice,
    workflow,
)
from winbot.commands._interactive import enforce_license, interactive_loop, render_results
from winbot.core.config import load_settings
from winbot.core.dispatcher import execute_natural_command, redact_command
from winbot.core.licensing import current_status
from winbot.core.logger import setup_logger
from winbot.ui.settings_window import SettingsWindow


def _configure_stdout() -> None:
    """Console Windows legacy usa cp1252; força UTF-8 para acentos em pt-BR."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


app = typer.Typer(
    name="winbot",
    help="WinBot CLI - Automação Profissional para Windows.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

app.add_typer(system.app, name="sys")
app.add_typer(workflow.app, name="workflow")
app.add_typer(schedule.app, name="schedule")
app.add_typer(rpa_tools.app, name="rpa")
app.add_typer(apps.app, name="apps")
app.add_typer(ai_cmd.app, name="ai")
app.add_typer(insights.app, name="insights")
app.add_typer(voice.app, name="voice")
app.add_typer(tray.app, name="tray")
app.add_typer(flow.app, name="flow")
app.add_typer(triggers_cmd.app, name="trigger")

console = Console()


@app.callback()
def _bootstrap() -> None:
    """Prepara encoding e sinks de log antes de qualquer comando."""
    _configure_stdout()
    setup_logger()
    try:
        from winbot.core.templates import install_default_templates

        install_default_templates()
    except Exception:
        pass


@app.command("version")
def version_cmd() -> None:
    """Exibe a versão atual do WinBot."""
    console.print(
        f"[bold cyan]WinBot Engine[/bold cyan] v{__version__} [dim](Enterprise Core)[/dim]"
    )


@app.command("license")
def license_cmd() -> None:
    """Exibe o HWID e o status da licença (validação 100% offline)."""
    status = current_status()
    style = "green" if status.state in {"LICENSED", "TRIAL"} else "red"
    table = Table(title="WinBot · Licenciamento", border_style="cyan")
    table.add_column("Campo", style="bold white")
    table.add_column("Valor")
    table.add_row("Status", f"[bold {style}]{status.state}[/bold {style}]")
    table.add_row("Detalhe", status.detail)
    table.add_row("HWID", status.hwid)
    table.add_row("Plano", status.plan or "-")
    table.add_row("Validade", status.expires or "-")
    console.print(table)


@app.command("do")
def do_cmd(
    pedido: Annotated[
        str,
        typer.Argument(
            help='Pedido em pt-BR, ex.: "abrir calc e esperar 1 segundos e fechar calc".'
        ),
    ],
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Simula o pedido sem executar nenhuma ação."),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Confirma automaticamente ações YELLOW/RED (automação)."),
    ] = False,
) -> None:
    """Executa um pedido em linguagem natural imediatamente, sem arquivo YAML."""
    settings = load_settings()
    enforce_license(settings)
    mode = "SIMULAÇÃO" if dry_run else "EXECUÇÃO"
    console.print(f"[dim]Pedido ({mode}):[/dim] {escape(redact_command(pedido))}")

    def _confirm(prompt: str) -> bool:
        answer = Prompt.ask(f"{prompt} [s/N]", console=console, default="n")
        return answer.strip().lower() in {"s", "sim", "y", "yes", "pode", "confirmo", "ok"}

    results = execute_natural_command(
        pedido,
        apply=not dry_run,
        policy=settings.security,
        confirm_fn=_confirm if (not dry_run and not yes) else None,
        auto_yes=yes,
    )
    render_results(results)
    if any(not item.ok or item.blocked for item in results):
        console.print("[bold red]Pedido interrompido (fail-closed).[/bold red]")
        raise typer.Exit(code=1)
    console.print(f"[bold green]{len(results)} ação(ões) concluída(s).[/bold green]")


@app.command("shell")
def shell_cmd(
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Simula todos os pedidos desta sessão."),
    ] = False,
) -> None:
    """Loop interativo: digite pedidos até 'sair' ou 'exit' (Ctrl+C também encerra)."""
    interactive_loop(
        prompt="winbot >",
        header=(
            "[bold cyan]WinBot Shell[/bold cyan] [dim]- pedidos em pt-BR; "
            "'sair'/'exit' encerra; Ctrl+C também.[/dim]"
        ),
        dry_run=dry_run,
        settings=load_settings(),
    )


@app.command("ui")
def ui_cmd() -> None:
    """Abre a Central de Configurações (Dark HUD)."""
    import sys as _sys

    from PySide6.QtWidgets import QApplication

    qt_app = QApplication.instance() or QApplication(_sys.argv)
    window = SettingsWindow()
    window.show()
    qt_app.exec()


if __name__ == "__main__":
    app()
