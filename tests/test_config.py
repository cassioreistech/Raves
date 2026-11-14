import pytest
from pydantic import ValidationError

from raves.core.config import (
    WorkflowDefinition,
    create_user_config,
    load_settings,
)


def test_defaults_carregam(tmp_path) -> None:
    settings = load_settings(path=tmp_path / "inexistente.yaml")
    assert settings.security.allow_shell is False
    assert settings.general.dry_run is True
    assert settings.licensing.enabled is False
    assert settings.licensing.trial_days == 14
    assert "powershell.exe" in settings.security.allowed_executables
    assert "notepad.exe" in settings.security.allowed_apps
    assert "lsass.exe" in settings.security.deny_processes
    assert settings.workspace_path().name == "RAVES"


def test_override_faz_merge(tmp_path) -> None:
    override = tmp_path / "settings.yaml"
    override.write_text("general:\n  log_level: DEBUG\n", encoding="utf-8")
    settings = load_settings(path=override)
    assert settings.general.log_level == "DEBUG"
    assert settings.general.dry_run is True
    assert settings.security.allow_shell is False
    assert settings.licensing.enabled is False


def test_chave_desconhecida_rejeitada(tmp_path) -> None:
    override = tmp_path / "settings.yaml"
    override.write_text("general:\n  inexistente: 1\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        load_settings(path=override)


def test_yaml_nao_mapeamento(tmp_path) -> None:
    override = tmp_path / "settings.yaml"
    override.write_text("- um\n- dois\n", encoding="utf-8")
    with pytest.raises(ValueError, match="mapeamento"):
        load_settings(path=override)


def test_create_user_config_e_idempotente(tmp_path) -> None:
    target = tmp_path / "RAVES" / "settings.yaml"
    created = create_user_config(path=target)
    assert created == target
    assert "allow_shell" in created.read_text(encoding="utf-8")
    created.write_text("custom: true\n", encoding="utf-8")
    create_user_config(path=target)
    assert "custom: true" in created.read_text(encoding="utf-8")


def test_workflow_schema_valido() -> None:
    wf = WorkflowDefinition.model_validate(
        {
            "name": "exemplo",
            "steps": [
                {
                    "name": "espera",
                    "action": "wait",
                    "params": {"seconds": 2},
                    "continue_on_error": True,
                }
            ],
        }
    )
    assert wf.steps[0].continue_on_error is True
    assert wf.steps[0].params["seconds"] == 2


def test_workflow_aceita_acoes_gui() -> None:
    wf = WorkflowDefinition.model_validate(
        {
            "name": "rpa",
            "steps": [
                {"name": "clique", "action": "gui_click", "params": {"x": 10, "y": 20}},
                {"name": "texto", "action": "gui_type", "params": {"text": "oi"}},
                {"name": "atalho", "action": "gui_hotkey", "params": {"keys": ["ctrl", "s"]}},
                {"name": "imagem", "action": "gui_click_image", "params": {"image": "a.png"}},
            ],
        }
    )
    assert [step.action for step in wf.steps] == [
        "gui_click",
        "gui_type",
        "gui_hotkey",
        "gui_click_image",
    ]


@pytest.mark.parametrize(
    "step",
    [
        {"name": "s", "action": "nuke.all"},
        {"name": "s", "action": "powershell", "params": {}},
        {"name": "s", "action": "launch_app", "params": {}},
        {"name": "s", "action": "gui_click", "params": {"x": 1}},
        {"name": "s", "action": "gui_hotkey", "params": {"keys": []}},
        {"name": "s", "action": "wait", "params": {"seconds": 999}},
        {"name": "s", "action": "wait", "typo": 1},
    ],
)
def test_workflow_schema_rejeita_invalido(step) -> None:
    with pytest.raises(ValidationError):
        WorkflowDefinition.model_validate({"name": "x", "steps": [step]})


def test_workflow_exige_ao_menos_um_step() -> None:
    with pytest.raises(ValidationError):
        WorkflowDefinition.model_validate({"name": "x", "steps": []})
