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
from winbot.commands import rpa_tools, schedule, system, workflow
from winbot.core.config import Settings, load_settings
from winbot.core.dispatcher import DispatchResult, execute_natural_command
from winbot.core.licensing import LicenseError, check_license_or_raise, current_status
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
app.add_typer(schedule.app, name="schedule")
app.add_typer(rpa_tools.app, name="rpa")

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


def _enforce_license(settings: Settings) -> None:
    """Mesmo gate comercial de `workflow run`, aplicado a `do` e `shell`."""
    if not settings.licensing.enabled:
        return
    try:
        check_license_or_raise()
    except LicenseError as exc:
        console.print(f"[bold red]Licença:[/bold red] {escape(str(exc))}")
        raise typer.Exit(code=1) from exc


def _status_icons() -> tuple[str, str]:
    """✔/✘ em UTF-8; fallback ASCII em console cp1252 (ver PLAN.md §7)."""
    encoding = (getattr(console.file, "encoding", "") or "").lower().replace("-", "")
    return ("✔", "✘") if "utf" in encoding else ("OK", "X")


def _render_results(results: list[DispatchResult]) -> None:
    ok_icon, bad_icon = _status_icons()
    for item in results:
        good = item.ok and not item.blocked
        icon = ok_icon if good else bad_icon
        color = "green" if good else "red"
        prefix = "BLOQUEADO: " if item.blocked else ""
        console.print(
            f"  [{color}]{icon}[/{color}] [bold]{escape(item.label)}[/bold] "
            f"[dim]{escape(prefix + item.message)}[/dim]"
        )


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
) -> None:
    """Executa um pedido em linguagem natural imediatamente, sem arquivo YAML."""
    settings = load_settings()
    _enforce_license(settings)
    mode = "SIMULAÇÃO" if dry_run else "EXECUÇÃO"
    console.print(f"[dim]Pedido ({mode}):[/dim] {escape(pedido)}")

    results = execute_natural_command(pedido, apply=not dry_run, policy=settings.security)
    _render_results(results)
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
    settings = load_settings()
    _enforce_license(settings)
    console.print(
        "[bold cyan]WinBot Shell[/bold cyan] [dim]- pedidos em pt-BR; "
        "'sair'/'exit' encerra; Ctrl+C também.[/dim]"
    )

    while True:
        try:
            pedido = Prompt.ask("winbot >", console=console).strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            break
        if not pedido:
            continue
        if pedido.casefold() in {"sair", "exit", "quit"}:
            break
        results = execute_natural_command(pedido, apply=not dry_run, policy=settings.security)
        _render_results(results)

    console.print("[dim]Até logo.[/dim]")


if __name__ == "__main__":
    app()
