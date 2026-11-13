from pathlib import Path

import yaml
from typer.testing import CliRunner

from winbot.commands.workflow import _execute_step
from winbot.core.config import SecuritySettings, WorkflowDefinition
from winbot.main import app

ROOT = Path(__file__).parents[1]
EXAMPLE = ROOT / "examples" / "demo.workflow.yaml"
BLOCKED = ROOT / "examples" / "bloqueado.workflow.yaml"


def _load(path: Path) -> WorkflowDefinition:
    return WorkflowDefinition.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def test_exemplo_valida() -> None:
    wf = _load(EXAMPLE)
    assert wf.steps
    assert wf.steps[0].action == "powershell"


def test_dry_run_nao_executa_nada(mocker) -> None:
    proc = mocker.patch("winbot.engine.shell.subprocess.run")
    popen = mocker.patch("winbot.engine.windows_api.subprocess.Popen")
    enum = mocker.patch("winbot.engine.windows_api.win32gui.EnumWindows")
    sleep = mocker.patch("winbot.commands.workflow.time.sleep")

    wf = _load(EXAMPLE)
    policy = SecuritySettings(allow_shell=False)
    outcomes = [_execute_step(step, policy=policy, dry_run=True) for step in wf.steps]

    assert len(outcomes) == len(wf.steps)
    assert all(item.ok and not item.blocked for item in outcomes)
    proc.assert_not_called()
    popen.assert_not_called()
    enum.assert_not_called()
    sleep.assert_not_called()


def test_violacao_e_fail_closed_mesmo_com_continue_on_error() -> None:
    result = CliRunner().invoke(app, ["workflow", "run", str(BLOCKED), "--apply"])
    assert result.exit_code == 1
    assert "BLOQUEADO" in result.stdout
    assert "Nunca deve rodar" not in result.stdout


def test_run_dry_run_padrao() -> None:
    result = CliRunner().invoke(app, ["workflow", "run", str(EXAMPLE)])
    assert result.exit_code == 0
    assert "concluído" in result.stdout.lower()


def test_workflow_list() -> None:
    result = CliRunner().invoke(app, ["workflow", "list"])
    assert result.exit_code == 0


def test_workflow_inexistente() -> None:
    result = CliRunner().invoke(app, ["workflow", "run", "nao_existe_xyz"])
    assert result.exit_code == 1
