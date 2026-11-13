"""Orquestrador principal da CLI."""

from __future__ import annotations

import sys

import typer
from rich.console import Console

from winbot import __version__
from winbot.commands import system, workflow
from winbot.core.logger import setup_logger


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

console = Console()


@app.callback()
def _bootstrap() -> None:
    """Prepara encoding e sinks de log antes de qualquer comando."""
    _configure_stdout()
    setup_logger()


@app.command("version")
def version_cmd() -> None:
    """Exibe a versão atual do WinBot."""
    console.print(
        f"[bold cyan]WinBot Engine[/bold cyan] v{__version__} [dim](Enterprise Core)[/dim]"
    )


if __name__ == "__main__":
    app()
