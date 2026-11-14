"""Núcleo Orbital Flutuante (HUD) — PySide6, 100% vetorial.

Janela frameless, always-on-top, fundo transparente, arrastável, com auto-hide
após 4s de inatividade. Desenha 3 anéis concêntricos assimétricos que reagem ao
estado (LISTENING/THINKING/SPEAKING/ERROR) e ao nível de áudio.
"""

from __future__ import annotations

import contextlib
from typing import Any

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QLineEdit, QWidget

from raves.ui.state_bridge import UiState

# Cores do tema Dark HUD.
COLOR_CYAN = QColor("#00E5FF")
COLOR_AMBER = QColor("#FFB300")
COLOR_VIOLET = QColor("#7C4DFF")
COLOR_GREEN = QColor("#00E676")
COLOR_CORAL = QColor("#FF5252")
COLOR_PANEL = QColor(11, 19, 36, 200)  # #0B1324 translúcido
COLOR_TEXT = QColor("#E0F7FA")

STATE_COLOR = {
    UiState.LISTENING.value: COLOR_CYAN,
    UiState.THINKING.value: COLOR_AMBER,
    UiState.SPEAKING.value: COLOR_GREEN,
    UiState.SUCCESS.value: COLOR_GREEN,
    UiState.ERROR.value: COLOR_CORAL,
}


class HudOverlay(QWidget):
    def __init__(self, bridge: Any, parent: Any = None) -> None:
        super().__init__(parent)
        self.bridge = bridge
        self._state = UiState.HIDDEN.value
        self._caption = ""
        self._level = 0.0
        self._angle1 = 0.0
        self._angle2 = 0.0
        self._angle3 = 0.0
        self._drag_pos: QPoint | None = None
        self._auto_hide_timer = QTimer(self)
        self._auto_hide_timer.setSingleShot(True)
        self._auto_hide_timer.timeout.connect(self._on_auto_hide)
        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._tick)
        self._anim_timer.start(16)  # ~60 FPS

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.resize(360, 130)
        self._position_default()

        self.text_input = QLineEdit(self)
        self.text_input.setPlaceholderText("Digite um pedido e Enter…")
        self.text_input.setGeometry(108, self.height() - 34, self.width() - 116, 24)
        self.text_input.setStyleSheet(
            "QLineEdit { background: rgba(11,19,36,0.85); color: #E0F7FA; "
            "border: 1px solid #00E5FF; border-radius: 6px; padding: 2px 6px; }"
        )
        self.text_input.returnPressed.connect(self._on_text_submitted)
        self.text_input.hide()

        bridge.state_changed.connect(self._on_state_changed)
        bridge.audio_level_changed.connect(self._on_level)
        bridge.show_hud.connect(self.show_animated)
        bridge.hide_hud.connect(self.hide_animated)

    def _position_default(self) -> None:
        from PySide6.QtGui import QGuiApplication

        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        self.move(geo.right() - self.width() - 24, geo.bottom() - self.height() - 24)

    # ------------------------------------------------------------------
    # Estado
    # ------------------------------------------------------------------

    def _on_state_changed(self, state: str, caption: str) -> None:
        self._state = state
        self._caption = caption or ""
        if state == UiState.HIDDEN.value:
            self.hide_animated()
        else:
            self.show_animated()

    def _on_level(self, level: float) -> None:
        self._level = max(0.0, min(1.0, float(level)))

    def show_animated(self) -> None:
        self.show()
        self.raise_()
        self.text_input.show()
        self.text_input.setFocus()
        self._auto_hide_timer.stop()
        if self._state not in (
            UiState.LISTENING.value,
            UiState.THINKING.value,
            UiState.SPEAKING.value,
        ):
            self._auto_hide_timer.start(4000)

    def hide_animated(self) -> None:
        self._auto_hide_timer.stop()
        self.text_input.hide()
        self.text_input.clear()
        self.hide()

    def _on_auto_hide(self) -> None:
        if self._state in (UiState.SUCCESS.value, UiState.ERROR.value, UiState.HIDDEN.value):
            self.hide()

    def _tick(self) -> None:
        if not self.isVisible():
            return
        speed = 1.0
        if self._state == UiState.LISTENING.value:
            speed = 1.5 + self._level * 2.0
        elif self._state == UiState.THINKING.value:
            speed = 4.0
        elif self._state == UiState.SPEAKING.value:
            speed = 2.5
        elif self._state == UiState.ERROR.value:
            speed = 0.5
        self._angle1 = (self._angle1 + speed * 1.0) % 360
        self._angle2 = (self._angle2 - speed * 1.7) % 360
        self._angle3 = (self._angle3 + speed * 0.6) % 360
        self.update()

    # ------------------------------------------------------------------
    # Interação
    # ------------------------------------------------------------------

    def mousePressEvent(self, event: Any) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: Any) -> None:
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event: Any) -> None:
        self._drag_pos = None

    def mouseDoubleClickEvent(self, event: Any) -> None:
        self.bridge.request_settings.emit()

    # ------------------------------------------------------------------
    # Teclado
    # ------------------------------------------------------------------

    def keyPressEvent(self, event: Any) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.hide_animated()
            event.accept()
            return
        super().keyPressEvent(event)

    def _on_text_submitted(self) -> None:
        text = self.text_input.text().strip()
        if not text:
            return
        self.text_input.clear()
        self._auto_hide_timer.stop()
        self.bridge.set_state("THINKING", text[:80])

        def worker() -> None:
            try:
                from raves.core.config import load_settings
                from raves.core.dispatcher import execute_natural_command

                settings = load_settings()
                results = execute_natural_command(text, apply=True, policy=settings.security)
                summary = " | ".join(item.message for item in results)[:120]
                ok = all(item.ok and not item.blocked for item in results)
                self.bridge.set_state("SUCCESS" if ok else "ERROR", summary or text[:80])
                # Fala a resposta se pyttsx3 estiver disponível (best-effort).
                try:
                    import pyttsx3

                    engine = pyttsx3.init()
                    engine.say(summary if ok else "Pedido interrompido.")
                    engine.runAndWait()
                    with contextlib.suppress(Exception):
                        engine.stop()
                except Exception:
                    pass
            except Exception as exc:
                self.bridge.set_state("ERROR", str(exc)[:80])

        import threading

        threading.Thread(target=worker, name="hud-text-submit", daemon=True).start()

    # ------------------------------------------------------------------
    # Renderização
    # ------------------------------------------------------------------

    def paintEvent(self, event: Any) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        color = STATE_COLOR.get(self._state, COLOR_CYAN)
        cx, cy = 60, self.height() // 2
        base_radius = 34

        # Painel glassmorphism (só se houver legenda).
        if self._caption:
            panel_rect = QRect(100, 18, self.width() - 110, self.height() - 36)
            painter.setPen(QPen(QColor(0, 229, 255, 60), 1))
            painter.setBrush(QBrush(COLOR_PANEL))
            painter.drawRoundedRect(panel_rect, 12, 12)
            painter.setPen(QPen(COLOR_TEXT))
            font = QFont("Segoe UI", 9)
            painter.setFont(font)
            painter.drawText(
                panel_rect.adjusted(10, 6, -10, -6),
                Qt.TextFlag.TextWordWrap
                | Qt.AlignmentFlag.AlignLeft
                | Qt.AlignmentFlag.AlignVCenter,
                self._caption[:120],
            )

        # Anel externo tracejado (telemetria).
        self._draw_ring(painter, cx, cy, base_radius + 16, color, self._angle1, 4, dashed=True)
        # Arco médio rotativo.
        self._draw_ring(
            painter, cx, cy, base_radius + 6, color, self._angle2, 6, dashed=False, span=120
        )
        # Núcleo central com barra de espectro.
        radius = (
            base_radius - 4 + int(self._level * 6)
            if self._state == UiState.LISTENING.value
            else base_radius - 4
        )
        painter.setPen(Qt.PenStyle.NoPen)
        grad = QRadialGradient(cx, cy, radius)
        grad.setColorAt(0.0, color.lighter(140))
        grad.setColorAt(0.6, color)
        grad.setColorAt(1.0, QColor(color.red(), color.green(), color.blue(), 40))
        painter.setBrush(QBrush(grad))
        painter.drawEllipse(cx - radius, cy - radius, radius * 2, radius * 2)

        # Ponto central.
        painter.setBrush(QBrush(QColor("#FFFFFF")))
        painter.drawEllipse(cx - 3, cy - 3, 6, 6)

    def _draw_ring(
        self,
        painter: QPainter,
        cx: int,
        cy: int,
        radius: int,
        color: QColor,
        angle: float,
        width: int,
        dashed: bool = False,
        span: int = 360,
    ) -> None:
        pen_color = QColor(color)
        pen_color.setAlpha(180 if dashed else 220)
        pen = QPen(pen_color, width, Qt.PenStyle.DashLine if dashed else Qt.PenStyle.SolidLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        rect = QRectF(cx - radius, cy - radius, radius * 2, radius * 2)
        painter.drawArc(rect, int(angle * 16), int(span * 16))
