"""Comandos de diagnóstico do sistema."""

from __future__ import annotations

import os

import psutil
import typer
from rich.console import Console
from rich.table import Table

from raves.core.logger import logger

app = typer.Typer(help="Operações e diagnósticos do sistema Windows.")
console = Console()


def _system_drive() -> str:
    """Resolve a unidade do sistema sem hardcodar ``C:\\``."""
    return f"{os.environ.get('SYSTEMDRIVE', 'C:')}\\"


@app.command("status")
def system_status() -> None:
    """Exibe métricas de saúde do Windows em tempo real."""
    logger.info("Executando diagnóstico de status do sistema.")

    cpu = psutil.cpu_percent(interval=0.5)
    ram = psutil.virtual_memory()
    disk = psutil.disk_usage(_system_drive())
    cores = psutil.cpu_count() or "?"

    table = Table(title="RAVES - Diagnóstico do Sistema", border_style="cyan")
    table.add_column("Recurso", style="bold white")
    table.add_column("Uso Atual", justify="right", style="green")
    table.add_column("Detalhes", style="dim")

    table.add_row("CPU", f"{cpu}%", f"{cores} núcleos lógicos")
    table.add_row(
        "Memória RAM",
        f"{ram.percent}%",
        f"{ram.used / (1024**3):.1f} GB / {ram.total / (1024**3):.1f} GB",
    )
    table.add_row("Disco", f"{disk.percent}%", f"{disk.free / (1024**3):.1f} GB livres")

    console.print(table)
