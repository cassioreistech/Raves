"""Ferramentas de inspeção para construir e depurar rotinas RPA."""

from __future__ import annotations

import time
from typing import Annotated

import typer
from rich.console import Console
from rich.live import Live
from rich.table import Table

from raves.engine import uia_engine

app = typer.Typer(help="Ferramentas de diagnóstico e inspeção RPA.")
console = Console()


def _snapshot(gui_module: object, win32gui_module: object) -> Table:
    x, y = gui_module.position()  # type: ignore[attr-defined]
    try:
        pixel = str(gui_module.pixel(x, y))  # type: ignore[attr-defined]
    except Exception:  # pixel pode falhar em telas remotas/seguras
        pixel = "indisponível"
    hwnd = win32gui_module.GetForegroundWindow()  # type: ignore[attr-defined]
    title = win32gui_module.GetWindowText(hwnd) or "(sem título)"  # type: ignore[attr-defined]

    table = Table(title="RAVES RPA Spy — Ctrl+C para sair", border_style="cyan")
    table.add_column("Campo", style="bold white")
    table.add_column("Valor")
    table.add_row("Mouse", f"x={x}  y={y}")
    table.add_row("Pixel RGB", pixel)
    table.add_row("Janela ativa", title)
    table.add_row("HWND", str(hwnd))
    return table


@app.command("spy")
def spy(
    refresh: Annotated[float, typer.Option("--refresh", help="Intervalo em segundos")] = 0.25,
) -> None:
    """Mostra posição do mouse, pixel e janela ativa em tempo real (Ctrl+C sai)."""
    import pyautogui
    import win32gui

    pyautogui.FAILSAFE = True
    interval = min(max(refresh, 0.1), 2.0)
    try:
        with Live(_snapshot(pyautogui, win32gui), console=console, refresh_per_second=4) as live:
            while True:
                live.update(_snapshot(pyautogui, win32gui))
                time.sleep(interval)
    except KeyboardInterrupt:
        console.print("\n[dim]Spy encerrado.[/dim]")


@app.command("inspect")
def inspect(
    title: Annotated[
        str,
        typer.Argument(help="Trecho do título da janela (case-insensitive)."),
    ],
    max_depth: Annotated[
        int, typer.Option("--depth", help="Profundidade máxima na árvore UIA")
    ] = 3,
) -> None:
    """Lista botões e campos detectados via UIA numa janela (para criar automações)."""
    try:
        controls = uia_engine.list_window_controls(title, max_depth=max_depth)
    except Exception as exc:
        console.print(f"[bold red]Erro:[/bold red] {exc}")
        raise typer.Exit(code=1) from exc

    if not controls:
        console.print(f"[yellow]Nenhum controle encontrado em '{title}'.[/yellow]")
        return

    table = Table(
        title=f"Controles UIA — {title} ({len(controls)} encontrados)",
        border_style="cyan",
    )
    table.add_column("#", justify="right", style="dim")
    table.add_column("Título", style="bold white", overflow="fold")
    table.add_column("Tipo", style="cyan")
    table.add_column("Auto ID", style="dim", overflow="fold")
    for index, control in enumerate(controls, start=1):
        table.add_row(
            str(index),
            control.get("title") or "(sem título)",
            control.get("control_type") or "-",
            control.get("auto_id") or "-",
        )
    console.print(table)
