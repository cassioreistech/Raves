"""Gravação e gestão de workflows (Sprint A)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from raves.core import database
from raves.engine.recorder import WorkflowRecorder

app = typer.Typer(help="Gravação e gestão de workflows.")
console = Console()


@app.command("record")
def record(
    name: Annotated[str, typer.Argument(help="Nome do workflow a gravar.")],
    output: Annotated[
        Path | None,
        typer.Option(
            "--output", "-o", help="Caminho do YAML (padrão: ~/.raves/workflows/<nome>.yaml)"
        ),
    ] = None,
) -> None:
    """Grava uma rotina manual e salva como workflow YAML pronto para execução."""
    recorder = WorkflowRecorder(name)
    console.print(f"[bold cyan]Gravando '{recorder.name}'...[/bold cyan]")
    console.print("[dim]Execute a rotina manualmente. ESC ou Ctrl+C encerra.[/dim]")
    try:
        recorder.record()
    except KeyboardInterrupt:
        recorder.stop()

    if not recorder.steps:
        console.print("[yellow]Nenhum passo gravado — arquivo não criado.[/yellow]")
        raise typer.Exit(code=1)

    try:
        path = recorder.save(output)
    except (OSError, ValueError) as exc:
        console.print(f"[bold red]Falha ao salvar:[/bold red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print(f"[bold green]{len(recorder.steps)} passo(s) salvos em {path}[/bold green]")
    database.log_command(f"flow record {name}", True, f"{len(recorder.steps)} passos")
