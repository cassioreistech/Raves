import subprocess

import pytest

from winbot.core.config import SecuritySettings
from winbot.core.security import SecurityViolationError
from winbot.engine import shell


@pytest.fixture
def policy() -> SecuritySettings:
    return SecuritySettings(allow_shell=True)


def test_dry_run_nao_executa(policy, mocker) -> None:
    proc = mocker.patch("winbot.engine.shell.subprocess.run")
    result = shell.run(["powershell.exe", "Get-Date"], policy, dry_run=True)
    assert result.simulated is True
    assert result.success is True
    proc.assert_not_called()


def test_execucao_usa_shell_false(policy, mocker) -> None:
    proc = mocker.patch("winbot.engine.shell.subprocess.run")
    proc.return_value.returncode = 0
    proc.return_value.stdout = "ok"
    proc.return_value.stderr = ""
    result = shell.run(["powershell.exe", "Get-Date"], policy, dry_run=False, timeout=7)
    assert result.simulated is False
    assert result.return_code == 0
    assert proc.call_args.kwargs["shell"] is False
    assert proc.call_args.kwargs["timeout"] == 7
    assert proc.call_args.kwargs["check"] is False


def test_timeout_retorna_falha(policy, mocker) -> None:
    proc = mocker.patch("winbot.engine.shell.subprocess.run")
    proc.side_effect = subprocess.TimeoutExpired("powershell.exe", 7)
    result = shell.run(["powershell.exe", "Get-Date"], policy, dry_run=False, timeout=7)
    assert result.success is False
    assert "Timeout" in result.stderr


def test_powershell_usando_api_publica(policy, mocker) -> None:
    proc = mocker.patch("winbot.engine.shell.subprocess.run")
    result = shell.run_powershell("Get-Date", timeout=7, policy=policy, dry_run=True)
    assert result.success is True
    assert result.argv[0] == "powershell.exe"
    assert "-NoProfile" in result.argv
    assert "-File" in result.argv
    proc.assert_not_called()


def test_powershell_com_script_perigoso_e_bloqueado(policy, mocker) -> None:
    proc = mocker.patch("winbot.engine.shell.subprocess.run")
    with pytest.raises(SecurityViolationError):
        shell.run_powershell("Invoke-Expression 'whoami'", policy=policy, dry_run=True)
    proc.assert_not_called()


def test_powershell_path_variavel_e_bloqueado(policy, mocker) -> None:
    proc = mocker.patch("winbot.engine.shell.subprocess.run")
    with pytest.raises(SecurityViolationError):
        shell.run_powershell(
            "Remove-Item -Force -Recurse $env:USERPROFILE", policy=policy, dry_run=True
        )
    proc.assert_not_called()
