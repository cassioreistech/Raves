from pathlib import Path

import yaml
from typer.testing import CliRunner

from raves.commands.workflow import _execute_step
from raves.core.config import SecuritySettings, WorkflowDefinition
from raves.main import app

ROOT = Path(__file__).parents[1]
EXAMPLE = ROOT / "examples" / "demo.workflow.yaml"
RPA_EXAMPLE = ROOT / "examples" / "rpa.workflow.yaml"
BLOCKED = ROOT / "examples" / "bloqueado.workflow.yaml"


def _load(path: Path) -> WorkflowDefinition:
    return WorkflowDefinition.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def test_exemplo_valida() -> None:
    wf = _load(EXAMPLE)
    assert wf.steps
    assert wf.steps[0].action == "powershell"


def test_dry_run_nao_executa_nada(mocker) -> None:
    proc = mocker.patch("raves.engine.shell.subprocess.run")
    popen = mocker.patch("raves.engine.windows_api.subprocess.Popen")
    enum = mocker.patch("raves.engine.windows_api.win32gui.EnumWindows")
    sleep = mocker.patch("raves.core.dispatcher.time.sleep")

    wf = _load(EXAMPLE)
    outcomes = [
        _execute_step(step, policy=SecuritySettings(allow_shell=False), dry_run=True)
        for step in wf.steps
    ]
    assert len(outcomes) == len(wf.steps)
    assert all(item.ok and not item.blocked for item in outcomes)
    proc.assert_not_called()
    popen.assert_not_called()
    enum.assert_not_called()
    sleep.assert_not_called()


def test_acoes_gui_em_dry_run_nao_encostam_no_pyautogui(mocker) -> None:
    mocker.patch("raves.engine.windows_api.screen_size", return_value=(1920, 1080))
    pag = mocker.patch("raves.engine.gui._pyautogui")
    wf = _load(RPA_EXAMPLE)
    outcomes = [_execute_step(step, policy=SecuritySettings(), dry_run=True) for step in wf.steps]
    assert all(item.ok for item in outcomes)
    pag.assert_not_called()


def test_hotkey_proibida_no_workflow_e_fail_closed() -> None:
    from raves.core.dispatcher import StepOutcome

    wf = WorkflowDefinition.model_validate(
        {
            "name": "perigoso",
            "steps": [
                {
                    "name": "atalho",
                    "action": "gui_hotkey",
                    "params": {"keys": ["ctrl", "alt", "delete"]},
                    "continue_on_error": True,
                }
            ],
        }
    )
    outcome = _execute_step(wf.steps[0], policy=SecuritySettings(), dry_run=False)
    assert isinstance(outcome, StepOutcome)
    assert outcome.blocked is True


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
    assert CliRunner().invoke(app, ["workflow", "list"]).exit_code == 0


def test_workflow_inexistente() -> None:
    assert CliRunner().invoke(app, ["workflow", "run", "nao_existe_xyz"]).exit_code == 1


def test_license_command() -> None:
    result = CliRunner().invoke(app, ["license"])
    assert result.exit_code == 0
    assert "HWID" in result.stdout
