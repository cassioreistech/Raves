import pytest
from typer.testing import CliRunner

from winbot.commands import schedule
from winbot.core.security import SecurityViolationError
from winbot.main import app


def test_nome_invalido_bloqueia() -> None:
    with pytest.raises(SecurityViolationError, match="inválido"):
        schedule._task_name("nome com espaco&")


def test_create_dry_run_nao_chama_schtasks(mocker) -> None:
    run = mocker.patch("winbot.commands.schedule.subprocess.run")
    result = CliRunner().invoke(app, ["schedule", "create", "demo", "examples/demo.workflow.yaml"])
    assert result.exit_code == 0
    run.assert_not_called()


def test_create_sc_invalido() -> None:
    result = CliRunner().invoke(app, ["schedule", "create", "demo", "x", "--sc", "NUKE"])
    assert result.exit_code != 0


def test_create_horario_invalido() -> None:
    result = CliRunner().invoke(app, ["schedule", "create", "demo", "x", "--at", "99:99"])
    assert result.exit_code != 0


def test_remove_dry_run_nao_chama_schtasks(mocker) -> None:
    run = mocker.patch("winbot.commands.schedule.subprocess.run")
    result = CliRunner().invoke(app, ["schedule", "remove", "demo"])
    assert result.exit_code == 0
    run.assert_not_called()


def test_argv_schtasks_usa_shell_false(mocker) -> None:
    run = mocker.patch("winbot.commands.schedule.subprocess.run")
    run.return_value.returncode = 0
    run.return_value.stdout = ""
    run.return_value.stderr = ""
    mocker.patch("winbot.commands.schedule.shutil.which", return_value="C:\\schtasks.exe")
    schedule._run_schtasks(["/Delete", "/TN", "WinBot-demo", "/F"], dry_run=False)
    assert run.call_args.kwargs["shell"] is False
