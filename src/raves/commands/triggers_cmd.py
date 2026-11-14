"""Gatilhos reativos event-driven (Sprint B)."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from raves.engine.triggers import TriggerManager, TriggerRule

app = typer.Typer(help="Gatilhos reativos (event-driven, ~0% CPU).")
console = Console()

_manager: TriggerManager | None = None


def _get_manager() -> TriggerManager:
    global _manager
    if _manager is None:
        _manager = TriggerManager()
    return _manager


@app.command("list")
def triggers_list() -> None:
    """Lista os gatilhos configurados e seus status."""
    manager = _get_manager()
    rules = manager.list_rules()
    if not rules:
        console.print("[yellow]Nenhum gatilho configurado. Use 'raves trigger add'.[/yellow]")
        console.print("[dim]Arquivo: ~/.raves/triggers.yaml[/dim]")
        return
    table = Table(title=f"Gatilhos ({len(rules)})", border_style="cyan")
    table.add_column("Nome", style="bold white")
    table.add_column("Evento")
    table.add_column("Filtro/Alvo", overflow="fold")
    table.add_column("Run", overflow="fold")
    table.add_column("Ativo", justify="center")
    for rule in rules:
        if rule["event"] == "file_created":
            filtro = f"{rule.get('path')} {', '.join(rule.get('extensions') or [])}".strip()
        else:
            filtro = rule.get("window_title") or "-"
        table.add_row(
            str(rule["name"]),
            str(rule["event"]),
            filtro,
            str(rule["run"]),
            "✔" if rule.get("enabled") else "✘",
        )
    console.print(table)


@app.command("add")
def triggers_add(
    name: Annotated[str, typer.Option("--name", help="Nome único do gatilho.")],
    event: Annotated[str, typer.Option("--event", help="file_created | window_opened.")],
    run: Annotated[
        str, typer.Option("--run", help="Workflow ou comando do dispatcher a executar.")
    ],
    path: Annotated[
        str | None, typer.Option("--path", help="Pasta a monitorar (file_created).")
    ] = None,
    ext: Annotated[
        str | None, typer.Option("--ext", help="Extensão (ex: .pdf). Repetível via vírgula.")
    ] = None,
    window: Annotated[
        str | None, typer.Option("--window", help="Substring do título (window_opened).")
    ] = None,
    debounce: Annotated[float, typer.Option("--debounce", help="Debounce em segundos.")] = 1.5,
) -> None:
    """Adiciona um gatilho em ~/.raves/triggers.yaml."""
    if event not in {"file_created", "window_opened"}:
        console.print("[bold red]Evento inválido. Use file_created ou window_opened.[/bold red]")
        raise typer.Exit(code=2)
    extensions = [item.strip() for item in (ext or "").split(",") if item.strip()]
    try:
        rule = TriggerRule(
            name=name,
            event=event,
            path=path,
            extensions=extensions,
            window_title=window,
            run=run,
            debounce_seconds=debounce,
        )
    except Exception as exc:
        console.print(f"[bold red]Regra inválida:[/bold red] {exc}")
        raise typer.Exit(code=2) from exc

    manager = _get_manager()
    manager.add(rule)
    console.print(f"[bold green]Gatilho '{name}' adicionado.[/bold green]")


@app.command("remove")
def triggers_remove(
    name: Annotated[str, typer.Argument(help="Nome do gatilho a remover.")],
) -> None:
    """Remove um gatilho pelo nome."""
    manager = _get_manager()
    if manager.remove(name):
        console.print(f"[bold green]Gatilho '{name}' removido.[/bold green]")
    else:
        console.print(f"[yellow]Gatilho '{name}' não encontrado.[/yellow]")
        raise typer.Exit(code=1)


@app.command("watch")
def triggers_watch() -> None:
    """Inicia o daemon de gatilhos reativos (Ctrl+C encerra)."""
    manager = _get_manager()

    def _executor(rule, context: str) -> None:
        # Se 'run' for um workflow existente, executa o workflow; senão dispatcher.
        from pathlib import Path

        from raves.core.dispatcher import execute_natural_command

        wf_path = Path.home() / ".raves" / "workflows" / f"{rule.run}.yaml"
        if wf_path.exists():
            import subprocess

            subprocess.Popen(
                ["raves", "workflow", "run", str(wf_path), "--apply"],
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
            return
        execute_natural_command(rule.run, apply=True)

    manager.set_executor(_executor)
    console.print("[bold cyan]RAVES Trigger Watch[/bold cyan] [dim]— Ctrl+C encerra.[/dim]")
    manager.start()
    try:
        while True:
            import time

            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        manager.stop()
        console.print("[dim]Trigger watch encerrado.[/dim]")
