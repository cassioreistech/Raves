from PySide6.QtWidgets import QApplication

from winbot.ui.state_bridge import VALID_STATES, StateBridge, UiState

_QAPP = QApplication.instance() or QApplication([])


def test_state_transitions_and_signal() -> None:
    bridge = StateBridge()
    received: list[tuple[str, str]] = []
    bridge.state_changed.connect(lambda s, c: received.append((s, c)))

    assert bridge.set_state(UiState.LISTENING.value, "ouvindo") is True
    assert bridge.state == "LISTENING"
    assert bridge.caption == "ouvindo"
    assert received == [("LISTENING", "ouvindo")]


def test_invalid_state_rejected() -> None:
    bridge = StateBridge()
    assert bridge.set_state("FOO") is False
    assert bridge.state == "HIDDEN"


def test_audio_level_clamped() -> None:
    bridge = StateBridge()
    levels: list[float] = []
    bridge.audio_level_changed.connect(levels.append)
    assert bridge.set_audio_level(1.5) == 1.0
    assert bridge.set_audio_level(-0.3) == 0.0
    assert bridge.set_audio_level(0.42) == 0.42
    assert levels == [1.0, 0.0, 0.42]


def test_request_signals() -> None:
    bridge = StateBridge()
    shows: list[bool] = []
    hides: list[bool] = []
    settings: list[bool] = []
    bridge.show_hud.connect(lambda: shows.append(True))
    bridge.hide_hud.connect(lambda: hides.append(True))
    bridge.open_settings.connect(lambda: settings.append(True))
    bridge.request_show()
    bridge.request_hide()
    bridge.request_settings()
    assert shows == [True] and hides == [True] and settings == [True]


def test_valid_states_contains_all() -> None:
    for state in ("HIDDEN", "LISTENING", "THINKING", "SPEAKING", "SUCCESS", "ERROR"):
        assert state in VALID_STATES
