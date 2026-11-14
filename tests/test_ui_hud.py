from PySide6.QtWidgets import QApplication

from winbot.ui.hud_overlay import HudOverlay
from winbot.ui.state_bridge import StateBridge

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


def test_hud_text_input_existe_e_esc_oculta(mocker) -> None:
    bridge = StateBridge()
    hud = HudOverlay(bridge)
    hud.show_animated()
    assert hud.text_input.isVisible() is True
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent

    event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    hud.keyPressEvent(event)
    assert hud.isVisible() is False


def test_hud_text_submit_dispara_worker(mocker) -> None:
    bridge = StateBridge()
    hud = HudOverlay(bridge)
    states: list[str] = []
    bridge.state_changed.connect(lambda s, c: states.append(s))
    mocker.patch("winbot.core.config.load_settings")
    mocker.patch(
        "winbot.core.dispatcher.execute_natural_command",
        return_value=[],
    )
    hud.text_input.setText("abrir calc")
    hud._on_text_submitted()
    assert hud.text_input.text() == ""
    # Worker thread runs async; give it a moment.
    import time

    time.sleep(0.3)
    assert "THINKING" in states
