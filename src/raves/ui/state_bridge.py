"""Barramento thread-safe de eventos para a UI (Etapa Visual).

QObject com sinais Qt: permite que threads de áudio/execução/bandeja publiquem
mudanças de estado sem bloquear o loop principal. Estados: HIDDEN, LISTENING,
THINKING, SPEAKING, SUCCESS, ERROR.
"""

from __future__ import annotations

from enum import StrEnum

from PySide6.QtCore import QObject, Signal


class UiState(StrEnum):
    HIDDEN = "HIDDEN"
    LISTENING = "LISTENING"
    THINKING = "THINKING"
    SPEAKING = "SPEAKING"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"


VALID_STATES = frozenset(state.value for state in UiState)


class StateBridge(QObject):
    """Barramento único de eventos UI. Thread-safe via sinais Qt."""

    state_changed = Signal(str, str)  # (estado, legenda curta)
    audio_level_changed = Signal(float)
    show_hud = Signal()
    hide_hud = Signal()
    open_settings = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._state = UiState.HIDDEN
        self._caption = ""
        self._level = 0.0

    @property
    def state(self) -> str:
        return self._state.value

    @property
    def caption(self) -> str:
        return self._caption

    @property
    def audio_level(self) -> float:
        return self._level

    def set_state(self, state: str, caption: str = "") -> bool:
        """Atualiza estado + legenda e emite sinal. Retorna False se inválido."""
        if state not in VALID_STATES:
            return False
        self._state = UiState(state)
        self._caption = caption or ""
        self.state_changed.emit(self._state.value, self._caption)
        return True

    def set_audio_level(self, level: float) -> float:
        """Normaliza para [0,1] e emite sinal."""
        clamped = max(0.0, min(1.0, float(level)))
        self._level = clamped
        self.audio_level_changed.emit(clamped)
        return clamped

    def request_show(self) -> None:
        self.show_hud.emit()

    def request_hide(self) -> None:
        self.hide_hud.emit()

    def request_settings(self) -> None:
        self.open_settings.emit()
