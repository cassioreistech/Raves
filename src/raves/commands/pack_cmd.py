"""Importação/exportação de packs (.winbotpack) — Etapa 9."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from raves.core import pack_manager

app = typer.Typer(help="Pacotes de workflows (.winbotpack).")
console = Console()


@app.command("export")
def pack_export(
    name: Annotated[str, typer.Argument(help="Nome do workflow a exportar.")],
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Pasta de destino (padrão: ~/Desktop)."),
    ] = None,
) -> None:
    """Gera um .winbotpack com o workflow e suas imagens referenciadas."""
    destination = output or (Path.home() / "Desktop")
    try:
        path = pack_manager.export_pack(name, destination)
    except (FileNotFoundError, OSError, ValueError) as exc:
        console.print(f"[bold red]Falha ao exportar:[/bold red] {exc}")
        raise typer.Exit(code=1) from exc
    console.print(f"[bold green]Pack exportado:[/bold green] {path}")


@app.command("import")
def pack_import(
    path: Annotated[Path, typer.Argument(help="Caminho do .winbotpack.")],
) -> None:
    """Valida integridade (SHA-256) e extrai o pack em ~/.winbot/workflows/."""
    try:
        message = pack_manager.import_pack(path)
    except (FileNotFoundError, ValueError, OSError) as exc:
        console.print(f"[bold red]Falha ao importar:[/bold red] {exc}")
        raise typer.Exit(code=1) from exc
    console.print(f"[bold green]{message}[/bold green]")
