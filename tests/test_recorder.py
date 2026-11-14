from pathlib import Path

import yaml

from raves.core.config import WorkflowDefinition
from raves.engine.recorder import WorkflowRecorder


def test_save_gera_yaml_valido(tmp_path: Path) -> None:
    recorder = WorkflowRecorder("demo", output_dir=tmp_path)
    recorder.steps = [
        {"name": "UIA: OK", "action": "uia_click", "params": {"window": "Win", "control": "OK"}},
        {"name": "clique (1,2)", "action": "gui_click", "params": {"x": 1, "y": 2}},
    ]
    path = recorder.save()
    assert path.exists()
    wf = WorkflowDefinition.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    assert wf.name == "demo"
    assert len(wf.steps) == 2
    assert wf.steps[0].action == "uia_click"


def test_save_sem_passos_levanta(tmp_path: Path) -> None:
    recorder = WorkflowRecorder("vazio", output_dir=tmp_path)
    try:
        recorder.save()
    except ValueError:
        return
    raise AssertionError("save() deveria falhar sem passos")


def test_semantic_step_cai_para_gui_click_quando_uia_falha(mocker) -> None:
    mocker.patch("pywinauto.Desktop", side_effect=RuntimeError("sem UIA"))
    recorder = WorkflowRecorder("x")
    step = recorder._semantic_step(10, 20)
    assert step["action"] == "gui_click"
    assert step["params"] == {"x": 10, "y": 20}


def test_semantic_step_gera_uia_click_quando_ha_controle(mocker) -> None:
    control = mocker.MagicMock()
    control.window_text.return_value = "OK"
    top = mocker.MagicMock()
    top.window_text.return_value = "Janela"
    control.top_level_parent.return_value = top
    desktop = mocker.MagicMock()
    desktop.from_point.return_value = control
    mocker.patch("pywinauto.Desktop", return_value=desktop)

    recorder = WorkflowRecorder("x")
    step = recorder._semantic_step(10, 20)
    assert step["action"] == "uia_click"
    assert step["params"] == {"window": "Janela", "control": "OK"}
