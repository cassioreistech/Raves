from typer.testing import CliRunner

from raves.main import app


def test_spy_sai_limpo_com_ctrl_c(mocker) -> None:
    mocker.patch("pyautogui.position", return_value=(10, 20))
    mocker.patch("pyautogui.pixel", return_value=(1, 2, 3))
    mocker.patch("win32gui.GetForegroundWindow", return_value=42)
    mocker.patch("win32gui.GetWindowText", return_value="Janela de teste")
    live = mocker.patch("raves.commands.rpa_tools.Live")
    live.return_value.__enter__.side_effect = KeyboardInterrupt

    result = CliRunner().invoke(app, ["rpa", "spy"])
    assert result.exit_code == 0
