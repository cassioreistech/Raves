"""Lembretes por voz/temporizador (Etapa 9, zero polling).

Usa ``threading.Timer`` daemon. Ao disparar, emite no StateBridge (se houver)
e aciona um callback de fala (TTS) para avisar o usuário.
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from raves.core.logger import logger


@dataclass
class _Reminder:
    message: str
    fire_at: datetime
    timer: threading.Timer
    cancelled: bool = False


class ReminderManager:
    """Singleton em memória. Sem arquivo, sem I/O em repouso."""

    _instance: ReminderManager | None = None

    def __new__(cls) -> ReminderManager:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self._reminders: list[_Reminder] = []
        self._lock: threading.Lock = threading.Lock()
        self._state_bridge: Any = None
        self._speak_fn: Callable[[str], None] | None = None
        self._initialized: bool = True

    def set_state_bridge(self, bridge: Any) -> None:
        self._state_bridge = bridge

    def set_speak_fn(self, fn: Callable[[str], None] | None) -> None:
        self._speak_fn = fn

    def schedule_reminder(self, delay_seconds: int, message: str) -> str:
        delay = max(1, min(int(delay_seconds), 86400))
        fire_at = datetime.now() + timedelta(seconds=delay)
        timer = threading.Timer(delay, self._fire, args=(message,))
        timer.daemon = True
        reminder = _Reminder(message=message, fire_at=fire_at, timer=timer)
        timer.name = f"raves-reminder-{id(reminder)}"
        with self._lock:
            self._reminders.append(reminder)
        timer.start()
        logger.info(f"reminder agendado: '{message}' em {delay}s")
        return f"Lembrete agendado para {delay} segundo(s): {message}"

    def _fire(self, message: str) -> None:
        # Emite no HUD.
        bridge = self._state_bridge
        if bridge is not None:
            try:
                bridge.request_show()
                bridge.set_state("SPEAKING", message)
            except Exception:
                pass
        # Fala (best-effort).
        speak = self._speak_fn
        if speak is not None:
            with contextlib.suppress(Exception):
                speak(message)

    def list_active(self) -> list[dict[str, Any]]:
        now = datetime.now()
        with self._lock:
            result = []
            for reminder in self._reminders:
                if reminder.cancelled:
                    continue
                if not reminder.timer.is_alive():
                    continue
                remaining = (reminder.fire_at - now).total_seconds()
                result.append(
                    {
                        "message": reminder.message,
                        "fire_at": reminder.fire_at.isoformat(timespec="seconds"),
                        "remaining_seconds": max(0, int(remaining)),
                    }
                )
            return result

    def cancel_all(self) -> int:
        count = 0
        with self._lock:
            for reminder in self._reminders:
                if not reminder.cancelled and reminder.timer.is_alive():
                    reminder.timer.cancel()
                    reminder.cancelled = True
                    count += 1
            self._reminders.clear()
        return count


def get_reminder_manager() -> ReminderManager:
    return ReminderManager()


def schedule_reminder(delay_seconds: int, message: str) -> str:
    return get_reminder_manager().schedule_reminder(delay_seconds, message)


def cancel_all_reminders() -> int:
    return get_reminder_manager().cancel_all()


def list_active_reminders() -> list[dict[str, Any]]:
    return get_reminder_manager().list_active()
