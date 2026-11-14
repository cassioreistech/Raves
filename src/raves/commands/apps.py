"""Gestão do índice de aplicativos instalados (Etapa 1 de Blindagem)."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from raves.core import database
from raves.engine.app_indexer import scan_and_index_windows_apps

app = typer.Typer(help="Índice de aplicativos instalados no Windows.")
console = Console()


@app.command("sync")
def apps_sync() -> None:
    """Varre Menu Iniciar + registro e atualiza o índice SQLite."""
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Varrendo Menu Iniciar e App Paths...", total=None)
        count = scan_and_index_windows_apps()
        progress.remove_task(task)

    console.print(f"[bold green]{count} aplicativo(s) indexado(s).[/bold green]")
    console.print(f"[dim]Banco: {database.db_path()}[/dim]")


@app.command("list")
def apps_list(
    filter_text: Annotated[
        str | None,
        typer.Option("--filter", help="Mostra apenas nomes que contêm este texto."),
    ] = None,
) -> None:
    """Lista os aplicativos indexados."""
    rows = database.get_apps(filter_text)
    if not rows:
        console.print("[yellow]Nenhum aplicativo indexado. Rode 'raves apps sync'.[/yellow]")
        return

    table = Table(title=f"Aplicativos indexados ({len(rows)})", border_style="cyan")
    table.add_column("Nome", style="bold white", no_wrap=True)
    table.add_column("Alvo", overflow="fold")
    table.add_column("Origem", style="dim", no_wrap=True)
    for row in rows:
        table.add_row(str(row["name"]), str(row["target_path"]), str(row["source"] or "-"))
    console.print(table)
