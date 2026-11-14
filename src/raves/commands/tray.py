"""RAVES na bandeja do sistema + HUD Orbital + Central de Configurações (Etapa Visual).

Roda o loop Qt principal integrando o ícone da bandeja (QSystemTrayIcon), o
HUD Orbital flutuante e um atalho global (Ctrl+Alt+Space). Tudo 100% local.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import typer
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from raves.ai.local_brain import shutdown_if_managed
from raves.commands.workflow import WORKFLOWS_DIR
from raves.core import database
from raves.engine.observer import ContextObserver
from raves.engine.triggers import TriggerManager
from raves.ui.hud_overlay import HudOverlay
from raves.ui.settings_window import SettingsWindow
from raves.ui.state_bridge import StateBridge

app = typer.Typer(help="Roda o RAVES discretamente na bandeja do sistema (HUD + Qt).")

_observer: ContextObserver | None = None
_observer_lock = threading.Lock()
_trigger_manager: TriggerManager | None = None
_voice_paused = False
_qt_app: QApplication | None = None
_settings_window: SettingsWindow | None = None
_hud: HudOverlay | None = None
_bridge: StateBridge | None = None
_hotkey_thread: threading.Thread | None = None
_hotkey_stop = threading.Event()
_tray_icon: QSystemTrayIcon | None = None


def _raves_argv() -> list[str]:
    exe = shutil.which("raves")
    if exe:
        return [exe]
    candidate = Path(sys.executable).parent / "raves.exe"
    if candidate.exists():
        return [str(candidate)]
    return [sys.executable, "-m", "raves"]


def _make_icon_pixmap() -> QPixmap:
    size = 64
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor("#1f3864"))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    font = QFont("Segoe UI", 32, QFont.Weight.Bold)
    painter.setFont(font)
    painter.setPen(QColor("#ffffff"))
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "W")
    painter.end()
    return pixmap


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


def _toggle_voice() -> None:
    global _voice_paused
    if _voice_paused:
        _start_observer()
        _voice_paused = False
    else:
        _stop_observer()
        _voice_paused = True
    if _tray_icon is not None:
        pass  # Qt não tem update_menu(); o rótulo é estático, mas a ação funciona.


def _voice_status_text() -> str:
    return "Pausar Voz" if not _voice_paused else "Ativar Voz"


def _open_shell() -> None:
    try:
        subprocess.Popen(
            _raves_argv() + ["shell"],
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )
    except OSError as exc:
        print(f"Falha ao abrir shell: {exc}")


def _open_settings() -> None:
    global _settings_window
    if _settings_window is None:
        _settings_window = SettingsWindow()
    _settings_window.show()
    _settings_window.raise_()
    _settings_window.activateWindow()


def _workflow_items() -> list[QAction]:
    actions: list[QAction] = []
    files = sorted(WORKFLOWS_DIR.glob("*.yaml")) if WORKFLOWS_DIR.exists() else []
    if not files:
        act = QAction("(nenhum workflow)", None)
        act.setEnabled(False)
        return [act]
    for path in files:

        def _run(wf_path: Path = path) -> None:
            try:
                subprocess.Popen(
                    _raves_argv() + ["workflow", "run", str(wf_path), "--apply"],
                    creationflags=subprocess.CREATE_NEW_CONSOLE,
                )
            except OSError as exc:
                print(f"Falha ao executar workflow: {exc}")

        action = QAction(path.stem, None)
        action.triggered.connect(_run)
        actions.append(action)
    return actions


def _quit_app() -> None:
    _stop_triggers()
    _stop_observer()
    shutdown_if_managed()
    if _qt_app is not None:
        _qt_app.quit()


def _assistente() -> None:
    if _bridge is None:
        return
    _bridge.request_show.emit()  # type: ignore[attr-defined]
    threading.Thread(target=_assistente_once, name="raves-assistente", daemon=True).start()


def _global_hotkey_loop() -> None:
    try:
        from pynput import keyboard
    except Exception:
        return
    pressed: set[str] = set()

    def on_press(key: Any) -> None:
        try:
            if key in (keyboard.Key.ctrl_l, keyboard.Key.ctrl_r, keyboard.Key.ctrl):
                pressed.add("ctrl")
            elif key in (keyboard.Key.alt_l, keyboard.Key.alt_r, keyboard.Key.alt):
                pressed.add("alt")
            elif key == keyboard.Key.space:
                pressed.add("space")
        except Exception:
            pass
        if {"ctrl", "alt", "space"} <= pressed and _bridge is not None:
            _assistente()
            pressed.clear()

    def on_release(key: Any) -> None:
        try:
            if key in (keyboard.Key.ctrl_l, keyboard.Key.ctrl_r, keyboard.Key.ctrl):
                pressed.discard("ctrl")
            elif key in (keyboard.Key.alt_l, keyboard.Key.alt_r, keyboard.Key.alt):
                pressed.discard("alt")
            elif key == keyboard.Key.space:
                pressed.discard("space")
        except Exception:
            pass

    with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
        _hotkey_stop.wait()
        listener.stop()


def _assistente_once() -> None:
    global _bridge
    bridge = _bridge
    if bridge is None:
        return
    try:
        from raves.core.config import load_settings
        from raves.engine.voice import VoiceEngine

        settings = load_settings()
        engine = VoiceEngine(state_bridge=bridge)
        engine.start()
        if engine._get_model() is None:
            bridge.set_state("ERROR", "Modelo Whisper ausente")
            engine.stop()
            return
        bridge.set_state("LISTENING", "Ouvindo...")
        text = engine.listen_once()
        if not text:
            bridge.set_state("HIDDEN", "")
            engine.stop()
            return
        from raves.core.dispatcher import execute_natural_command

        results = execute_natural_command(text, apply=True, policy=settings.security)
        summary = " | ".join(item.message for item in results)[:120]
        ok = all(item.ok and not item.blocked for item in results)
        bridge.set_state("SUCCESS" if ok else "ERROR", summary or text[:80])
        if ok:
            engine.speak(f"{len(results)} ação concluída.")
        else:
            engine.speak("Pedido interrompido.")
        engine.stop()
    except Exception as exc:
        if bridge is not None:
            bridge.set_state("ERROR", str(exc)[:80])


def _build_tray_icon() -> QSystemTrayIcon:
    global _tray_icon
    icon = QSystemTrayIcon()
    icon.setIcon(QIcon(_make_icon_pixmap()))
    icon.setToolTip("RAVES")

    menu = QMenu()
    act_show = QAction("Chamar Assistente (Ctrl+Alt+Space)", icon)

    act_show.triggered.connect(_assistente)
    menu.addAction(act_show)

    act_settings = QAction("Abrir Configurações", icon)
    act_settings.triggered.connect(_open_settings)
    menu.addAction(act_settings)

    act_toggle = QAction("Pausar Voz", icon)
    act_toggle.triggered.connect(_toggle_voice)
    menu.addAction(act_toggle)

    wf_menu = QMenu("Executar Workflow")
    for action in _workflow_items():
        wf_menu.addAction(action)
    menu.addMenu(wf_menu)

    menu.addSeparator()
    act_quit = QAction("Sair", icon)
    act_quit.triggered.connect(_quit_app)
    menu.addAction(act_quit)

    icon.setContextMenu(menu)
    icon.activated.connect(
        lambda reason: (
            _open_settings() if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None
        )
    )
    _tray_icon = icon
    return icon


def _run_tray() -> None:
    global _qt_app, _hud, _bridge, _hotkey_thread
    import sys as _sys

    database.init_db()
    _start_observer()
    _start_triggers()

    instance = QApplication.instance()
    _qt_app = instance if isinstance(instance, QApplication) else QApplication(_sys.argv)
    _bridge = StateBridge()
    _hud = HudOverlay(_bridge)

    tray_icon = _build_tray_icon()
    tray_icon.show()

    # Apresentacao inicial premium (audio + HUD).
    try:
        from raves.commands._interactive import build_intro_greeting, speak_text

        intro = build_intro_greeting()
        if _bridge is not None:
            _bridge.set_state("LISTENING", intro)
            _bridge.request_show()
        speak_text(intro)
    except Exception:
        pass

    _hotkey_stop.clear()
    _hotkey_thread = threading.Thread(target=_global_hotkey_loop, name="raves-hotkey", daemon=True)
    _hotkey_thread.start()

    assert _qt_app is not None
    _qt_app.exec()

    _hotkey_stop.set()
    if _hotkey_thread is not None:
        _hotkey_thread.join(timeout=1.0)
    _stop_triggers()
    _stop_observer()
    shutdown_if_managed()


@app.callback(invoke_without_command=True)
def tray(ctx: typer.Context) -> None:
    """Roda o RAVES na bandeja do sistema (HUD Orbital + Central de Configurações)."""
    if ctx.invoked_subcommand is not None:
        return
    _run_tray()
