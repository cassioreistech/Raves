from unittest.mock import MagicMock

import raves.engine.uia_engine as uia_engine


def _desktop_with(windows):
    desktop = MagicMock()
    desktop.windows.return_value = windows
    return desktop


def test_wait_for_window_encontra_janela_visivel(mocker) -> None:
    window = MagicMock()
    window.window_text.return_value = "Calculadora"
    window.is_visible.return_value = True
    mocker.patch.object(uia_engine, "_desktop", return_value=_desktop_with([window]))
    assert uia_engine.wait_for_window("Calculadora", timeout=1) is True


def test_wait_for_window_retorna_false_quando_ausente(mocker) -> None:
    desktop = _desktop_with([])
    mocker.patch.object(uia_engine, "_desktop", return_value=desktop)
    assert uia_engine.wait_for_window("Inexistente", timeout=1) is False


def test_click_control_sucesso_invoca_controle(mocker) -> None:
    control = MagicMock()
    window = MagicMock()
    window.window_text.return_value = "Calculadora"
    window.child_window.return_value = control
    control.wait = MagicMock()
    desktop = _desktop_with([window])
    mocker.patch.object(uia_engine, "_desktop", return_value=desktop)

    ok, message = uia_engine.click_control("Calculadora", "Cinco", "Button")
    assert ok is True
    control.invoke.assert_called_once()
    assert "Cinco" in message


def test_click_control_falha_retorna_tuple(mocker) -> None:
    desktop = _desktop_with([])
    mocker.patch.object(uia_engine, "_desktop", return_value=desktop)
    ok, message = uia_engine.click_control("Nope", "X", None)
    assert ok is False
    assert "não encontrada" in message


def test_fill_field_usa_set_edit_text_e_enter(mocker) -> None:
    control = MagicMock()
    window = MagicMock()
    window.window_text.return_value = "Bloco"
    window.child_window.return_value = control
    control.wait = MagicMock()
    desktop = _desktop_with([window])
    mocker.patch.object(uia_engine, "_desktop", return_value=desktop)

    ok, message = uia_engine.fill_field("Bloco", "Editor", "Olá", press_enter=True)
    assert ok is True
    control.set_edit_text.assert_called_once_with("Olá")
    control.type_keys.assert_called_once_with("{ENTER}")


def test_fill_field_fallback_clipboard_quando_set_edit_falha(mocker) -> None:
    control = MagicMock()
    control.set_edit_text.side_effect = RuntimeError("não suportado")
    window = MagicMock()
    window.window_text.return_value = "Bloco"
    window.child_window.return_value = control
    control.wait = MagicMock()
    desktop = _desktop_with([window])
    mocker.patch.object(uia_engine, "_desktop", return_value=desktop)
    mocker.patch("pyperclip.copy")

    ok, message = uia_engine.fill_field("Bloco", "Editor", "Olá")
    assert ok is True
    control.type_keys.assert_called_once_with("^v", with_spaces=True)


def test_list_window_controls_retorna_estrutura(mocker) -> None:
    child = MagicMock()
    child.window_text.return_value = "OK"
    child.element_info.control_type = "Button"
    child.element_info.automation_id = "btnOK"
    child.children.return_value = []
    window = MagicMock()
    window.window_text.return_value = "Win"
    window.children.return_value = [child]
    desktop = _desktop_with([window])
    mocker.patch.object(uia_engine, "_desktop", return_value=desktop)

    result = uia_engine.list_window_controls("Win", max_depth=2)
    assert result == [{"title": "OK", "control_type": "Button", "auto_id": "btnOK"}]


def test_foreground_window_title(mocker) -> None:
    mocker.patch("win32gui.GetForegroundWindow", return_value=123)
    mocker.patch("win32gui.GetWindowText", return_value="Calculadora")
    assert uia_engine.foreground_window_title() == "Calculadora"
