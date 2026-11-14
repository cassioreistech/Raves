from PySide6.QtWidgets import QApplication

from winbot.core import database
from winbot.ui.settings_window import SettingsWindow

_QAPP = QApplication.instance() or QApplication([])


def test_settings_window_cria_abas() -> None:
    window = SettingsWindow()
    assert window.tabs.count() == 4
    assert window.tabs.tabText(0) == "Voz & Áudio"
    assert window.tabs.tabText(3) == "Perfil & Licença"


def test_settings_window_mostra_interesses(mocker) -> None:
    database.upsert_interest("musica", "lofi")
    window = SettingsWindow()
    window._refresh_interests()
    items = [window.interests_list.item(i).text() for i in range(window.interests_list.count())]
    assert any("lofi" in item for item in items)


def test_settings_window_license_label() -> None:
    window = SettingsWindow()
    assert "HWID" in window.license_label.text() or "Status" in window.license_label.text()
