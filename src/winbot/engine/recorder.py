"""Gravador inteligente de workflows (Sprint A, 100% local).

Monitora cliques do mouse e, no exato momento de cada clique esquerdo, consulta o
controle UIA sob o cursor para gerar um passo semântico (``uia_click``), caindo
para ``gui_click`` quando não houver controle acessível. Ao pressionar ESC (ou
Ctrl+C) salva um YAML compatível com ``WorkflowDefinition`` em
``~/.winbot/workflows/<nome>.yaml``.

Nenhuma rede, nenhum serviço externo. pynput é importado sob demanda.
"""

from __future__ import annotations

import contextlib
import time
from pathlib import Path
from typing import Any

import yaml

from winbot.core.logger import logger

_DEDUP_SECONDS = 0.3


class WorkflowRecorder:
    def __init__(self, name: str, output_dir: Path | None = None) -> None:
        self.name = name.strip() or "rotina_gravada"
        self.output_dir = output_dir or (Path.home() / ".winbot" / "workflows")
        self.steps: list[dict[str, Any]] = []
        self._running = False
        self._last_click: tuple[float, int, int, str] = (0.0, -1, -1, "")
        self._mouse_listener: Any = None
        self._key_listener: Any = None

    # ------------------------------------------------------------------
    # Captura
    # ------------------------------------------------------------------

    def _semantic_step(self, x: int, y: int) -> dict[str, Any]:
        """Tenta gerar uia_click; cai para gui_click se não houver controle."""
        window_title = ""
        control_title = ""
        try:
            from pywinauto import Desktop

            control = Desktop(backend="uia").from_point(x, y)
            control_title = (control.window_text() or "").strip()
            try:
                window_title = (control.top_level_parent().window_text() or "").strip()
            except Exception:
                window_title = ""
        except Exception as exc:
            logger.debug(f"recorder: UIA indisponível em ({x},{y}): {exc}")

        if control_title:
            return {
                "name": f"UIA: {control_title}",
                "action": "uia_click",
                "params": {"window": window_title, "control": control_title},
            }
        return {
            "name": f"clique ({x}, {y})",
            "action": "gui_click",
            "params": {"x": x, "y": y},
        }

    def _on_click(self, x: int, y: int, button: Any, pressed: bool) -> None:
        try:
            from pynput.mouse import Button

            if not pressed or button != Button.left:
                return
        except Exception:
            if not pressed:
                return

        now = time.monotonic()
        if now - self._last_click[0] < _DEDUP_SECONDS and (x, y) == (
            self._last_click[1],
            self._last_click[2],
        ):
            return
        self._last_click = (now, x, y, "")

        step = self._semantic_step(x, y)
        self.steps.append(step)

    def _on_press(self, key: Any) -> bool | None:
        try:
            from pynput.keyboard import Key

            if key == Key.esc:
                self.stop()
                return False
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------

    def start(self) -> None:
        from pynput import keyboard, mouse

        self._mouse_listener = mouse.Listener(on_click=self._on_click)
        self._key_listener = keyboard.Listener(on_press=self._on_press)
        self._mouse_listener.start()
        self._key_listener.start()
        self._running = True

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        for listener in (self._mouse_listener, self._key_listener):
            if listener is not None:
                with contextlib.suppress(Exception):
                    listener.stop()
        self._mouse_listener = None
        self._key_listener = None

    def record(self) -> None:
        """Bloqueia até ESC/Ctrl+C. Salva automaticamente ao encerrar."""
        self.start()
        try:
            while self._running:
                time.sleep(0.2)
        except KeyboardInterrupt:
            self.stop()
        finally:
            if self._running:
                self.stop()

    def save(self, path: Path | None = None) -> Path:
        if not self.steps:
            raise ValueError("nenhum passo gravado")
        target = path or (self.output_dir / f"{self.name}.yaml")
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "name": self.name,
            "description": "Gravado automaticamente pelo WinBot (Sprint A).",
            "steps": self.steps,
        }
        target.write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False, default_flow_style=False),
            encoding="utf-8",
        )
        return target
