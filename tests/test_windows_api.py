import pytest

from raves.core.config import SecuritySettings
from raves.core.security import SecurityViolationError
from raves.engine import windows_api


def test_snapshot(mocker) -> None:
    api = mocker.patch("raves.engine.windows_api.win32api")
    proc = mocker.patch("raves.engine.windows_api.win32process")
    api.GetComputerName.return_value = "TECH_ONE"
    api.GetUserName.return_value = "cassi"
    api.GetSystemMetrics.side_effect = [1920, 1080]
    proc.EnumProcesses.return_value = [1, 2, 3]

    snap = windows_api.system_snapshot()
    assert snap["computer"] == "TECH_ONE"
    assert snap["process_count"] == 3
    assert snap["screen"] == (1920, 1080)


def test_launch_app_nunca_usa_shell_true(mocker) -> None:
    popen = mocker.patch("raves.engine.windows_api.subprocess.Popen")
    ok = windows_api.launch_app("notepad.exe", dry_run=False, policy=SecuritySettings())
    assert ok is True
    assert popen.call_args.kwargs["shell"] is False


def test_launch_app_rejeita_metacaractere(mocker) -> None:
    popen = mocker.patch("raves.engine.windows_api.subprocess.Popen")
    with pytest.raises(SecurityViolationError, match="metacaractere"):
        windows_api.launch_app("calc.exe & format C:", dry_run=False, policy=SecuritySettings())
    popen.assert_not_called()


def test_launch_app_rejeita_app_fora_da_allowlist(mocker) -> None:
    popen = mocker.patch("raves.engine.windows_api.subprocess.Popen")
    with pytest.raises(SecurityViolationError, match="não permitido"):
        windows_api.launch_app("cmd.exe", dry_run=False, policy=SecuritySettings())
    popen.assert_not_called()


def test_kill_process_protege_sistema() -> None:
    with pytest.raises(SecurityViolationError, match="protegido"):
        windows_api.kill_process_by_name("lsass.exe", dry_run=False, policy=SecuritySettings())


def test_focus_window_dry_run_nao_enumera(mocker) -> None:
    enum = mocker.patch("raves.engine.windows_api.win32gui.EnumWindows")
    assert windows_api.focus_window("Notas", dry_run=True) is True
    enum.assert_not_called()
