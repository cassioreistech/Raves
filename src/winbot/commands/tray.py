"""WinBot na bandeja do sistema (System Tray) — Etapa 4 de Blindagem.

Roda discretamente ao lado do relógio do Windows. Menu: Ativar/Pausar Voz,
Abrir Shell, Executar Workflow, Sair. Sem janela de console enquanto em segundo
plano. 100% local.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import typer
from PIL import Image, ImageDraw, ImageFont
from rich.console import Console

from winbot.commands.workflow import WORKFLOWS_DIR
from winbot.core import database
from winbot.engine.observer import ContextObserver
from winbot.engine.triggers import TriggerManager

app = typer.Typer(help="Roda o WinBot discretamente na bandeja do sistema.")
console = Console()

_observer: ContextObserver | None = None
_observer_lock = threading.Lock()
_trigger_manager: TriggerManager | None = None
_voice_paused = False


def _winbot_argv() -> list[str]:
    """Resolve o executável do WinBot (instalado ou venv de desenvolvimento)."""
    exe = shutil.which("winbot")
    if exe:
        return [exe]
    candidate = Path(sys.executable).parent / "winbot.exe"
    if candidate.exists():
        return [str(candidate)]
    return [sys.executable, "-m", "winbot"]


def _make_icon() -> Image.Image:
    """Ícone simples gerado em memória (sem arquivo externo)."""
    size = 64
    image = Image.new("RGB", (size, size), "#1f3864")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("segoeui.ttf", 40)
    except OSError:
        font = ImageFont.load_default()
    draw.text((size // 2, size // 2), "W", fill="#ffffff", font=font, anchor="mm")
    return image


def _start_observer() -> None:
    global _observer
    with _observer_lock:
        if _observer is not None and _observer.running:
            return
        observer = ContextObserver()
        observer.start_background_watch()
        _observer = observer


def _stop_observer() -> None:
    global _observer
    with _observer_lock:
        if _observer is not None:
            _observer.stop()
            _observer = None


def _start_triggers() -> None:
    global _trigger_manager
    if _trigger_manager is not None:
        return
    manager = TriggerManager()
    _trigger_manager = manager
    manager.start()


def _stop_triggers() -> None:
    global _trigger_manager
    if _trigger_manager is not None:
        _trigger_manager.stop()
        _trigger_manager = None


def _toggle_voice(icon: Any, item: Any) -> None:
    global _voice_paused
    if _voice_paused:
        _start_observer()
        _voice_paused = False
    else:
        _stop_observer()
        _voice_paused = True
    # Atualiza o menu (pystray recria o menu a cada clique se for callable).
    icon.update_menu()


def _voice_status_text(item: Any) -> str:
    return "Pausar Voz" if not _voice_paused else "Ativar Voz"


def _open_shell(icon: Any, item: Any) -> None:
    try:
        subprocess.Popen(
            _winbot_argv() + ["shell"],
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )
    except OSError as exc:
        console.print(f"[bold red]Falha ao abrir shell:[/bold red] {exc}")


def _workflow_items() -> list[Any]:
    import pystray

    files = sorted(WORKFLOWS_DIR.glob("*.yaml")) if WORKFLOWS_DIR.exists() else []
    if not files:
        return [pystray.MenuItem("(nenhum workflow)", None, enabled=False)]
    items = []
    for path in files:

        def _run(wf_path: Path = path) -> None:
            try:
                subprocess.Popen(
                    _winbot_argv() + ["workflow", "run", str(wf_path), "--apply"],
                    creationflags=subprocess.CREATE_NEW_CONSOLE,
                )
            except OSError as exc:
                console.print(f"[bold red]Falha ao executar workflow:[/bold red] {exc}")

        items.append(pystray.MenuItem(path.stem, lambda _icon, _item, fn=_run: fn()))
    return items


def _quit(icon: Any, item: Any) -> None:
    _stop_observer()
    icon.stop()


@app.callback(invoke_without_command=True)
def tray(ctx: typer.Context) -> None:
    """Roda o WinBot discretamente na bandeja do sistema (Ctrl+C não se aplica)."""
    if ctx.invoked_subcommand is not None:
        return
    _run_tray()


def _run_tray() -> None:
    import pystray

    database.init_db()
    _start_observer()
    _start_triggers()

    menu = pystray.Menu(
        pystray.MenuItem(_voice_status_text, _toggle_voice),
        pystray.MenuItem("Abrir Shell", _open_shell),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Executar Workflow", pystray.Menu(*_workflow_items())),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Sair", _quit),
    )

    icon = pystray.Icon("winbot", _make_icon(), "WinBot", menu)
    try:
        icon.run()
    finally:
        _stop_triggers()
        _stop_observer()
        console.print("[dim]WinBot Tray encerrado.[/dim]")
