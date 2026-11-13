import pytest

from winbot.core.config import SecuritySettings
from winbot.core.security import (
    HARD_DENY,
    SecurityError,
    SecurityViolationError,
    check_command,
    enforce,
    validate_shell_command,
)


@pytest.fixture
def policy() -> SecuritySettings:
    return SecuritySettings(allow_shell=True)


@pytest.mark.parametrize(
    "fragment",
    [
        "Remove-Item C:\\tmp -Recurse -Force",
        "Invoke-Expression 'whoami'",
        "reg delete HKLM\\Software /f",
        "Stop-Computer -Force",
        "del /s /q C:\\Windows",
    ],
)
def test_hard_deny_bloqueia(fragment, policy) -> None:
    decision = check_command(["powershell.exe", "-Command", fragment], policy)
    assert not decision.allowed
    assert "padrão negado" in decision.reason


# Falsos negativos da blacklist original: ordem invertida, path variável, sem "c:\".
@pytest.mark.parametrize(
    "command",
    [
        "format C: /FS:NTFS",
        "Remove-Item $env:USERPROFILE -Recurse -Force",
        "Remove-Item -Force -Recurse D:\\dados",
        "Remove-Item ~ -Recurse",
        "Format-Volume -DriveLetter C -Confirm:$false",
        "rd /q /s D:\\backup",
        "bcdedit /delete {current}",
        "reg delete HKLM\\Software\\X /f",
    ],
)
def test_validate_shell_command_bloqueia(command) -> None:
    with pytest.raises(SecurityViolationError, match="bloqueado"):
        validate_shell_command(command)


def test_validate_shell_command_aceita_comando_seguro() -> None:
    validate_shell_command("Get-ChildItem $env:TEMP | Select-Object -First 5 Name")


def test_security_error_e_alias() -> None:
    assert SecurityError is SecurityViolationError


def test_deny_pattern_da_config() -> None:
    policy_local = SecuritySettings(allow_shell=True, deny_patterns=[r"Get-Secret"])
    assert not check_command(["powershell.exe", "-Command", "Get-Secret"], policy_local).allowed


def test_executavel_fora_da_allowlist(policy) -> None:
    decision = check_command(["net.exe", "user"], policy)
    assert not decision.allowed
    assert "não permitido" in decision.reason


def test_comando_valido(policy) -> None:
    assert check_command(["powershell.exe", "-Command", "Get-Date"], policy).allowed


def test_argv_vazio(policy) -> None:
    assert not check_command([], policy).allowed


def test_check_command_e_puro(policy, mocker) -> None:
    audit_mock = mocker.patch("winbot.core.security.audit")
    check_command(["powershell.exe", "Get-Date"], policy)
    audit_mock.assert_not_called()


def test_enforce_bloqueia_shell_desligado() -> None:
    with pytest.raises(SecurityError, match="allow_shell"):
        enforce(["powershell.exe", "Get-Date"], SecuritySettings(), dry_run=False)


def test_enforce_dry_run_permitido_com_shell_desligado() -> None:
    assert enforce(["powershell.exe", "Get-Date"], SecuritySettings(), dry_run=True).allowed


def test_hard_deny_nao_pode_ser_liberado() -> None:
    policy_local = SecuritySettings(allow_shell=True, deny_patterns=[])
    assert len(HARD_DENY) > 0
    assert not check_command(
        ["powershell.exe", "-Command", "Invoke-Expression 'x'"], policy_local
    ).allowed
