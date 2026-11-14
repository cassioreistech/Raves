from PySide6.QtWidgets import QApplication

from raves.ui.hud_overlay import HudOverlay
from raves.ui.state_bridge import StateBridge

_QAPP = QApplication.instance() or QApplication([])


def test_hud_overlay_cria_e_renderiza() -> None:
    bridge = StateBridge()
    hud = HudOverlay(bridge)
    assert hud.isVisible() is False
    bridge.set_state("LISTENING", "ouvindo")
    hud.show_animated()
    assert hud.isVisible() is True
    # Renderização não deve lançar.
    hud.update()
    hud.repaint()


def test_hud_overlay_auto_hide_timer() -> None:
    bridge = StateBridge()
    hud = HudOverlay(bridge)
    bridge.set_state("SUCCESS", "ok")
    hud.show_animated()
    assert hud._auto_hide_timer.isActive() is True


def test_hud_overlay_drag_handle() -> None:
    bridge = StateBridge()
    hud = HudOverlay(bridge)
    assert hud._drag_pos is None


def test_hud_esc_oculta() -> None:
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent

    bridge = StateBridge()
    hud = HudOverlay(bridge)
    hud.show_animated()
    assert hud.isVisible() is True
    event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    hud.keyPressEvent(event)
    assert hud.isVisible() is False
