import pytest
from pydantic import ValidationError

from winbot.core.config import (
    WorkflowDefinition,
    create_user_config,
    load_settings,
)


def test_defaults_carregam(tmp_path) -> None:
    settings = load_settings(path=tmp_path / "inexistente.yaml")
    assert settings.security.allow_shell is False
    assert settings.general.dry_run is True
    assert "powershell.exe" in settings.security.allowed_executables
    assert "notepad.exe" in settings.security.allowed_apps
    assert "lsass.exe" in settings.security.deny_processes
    assert settings.workspace_path().name == "WinBot"


def test_override_faz_merge(tmp_path) -> None:
    override = tmp_path / "settings.yaml"
    override.write_text("general:\n  log_level: DEBUG\n", encoding="utf-8")
    settings = load_settings(path=override)
    assert settings.general.log_level == "DEBUG"
    assert settings.general.dry_run is True
    assert settings.security.allow_shell is False


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
    target = tmp_path / "WinBot" / "settings.yaml"
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


@pytest.mark.parametrize(
    "step",
    [
        {"name": "s", "action": "nuke.all"},
        {"name": "s", "action": "powershell", "params": {}},
        {"name": "s", "action": "launch_app", "params": {}},
        {"name": "s", "action": "wait", "params": {"seconds": 999}},
        {"name": "s", "action": "wait", "params": {"seconds": -1}},
        {"name": "s", "action": "wait", "typo": 1},
    ],
)
def test_workflow_schema_rejeita_invalido(step) -> None:
    with pytest.raises(ValidationError):
        WorkflowDefinition.model_validate({"name": "x", "steps": [step]})


def test_workflow_exige_ao_menos_um_step() -> None:
    with pytest.raises(ValidationError):
        WorkflowDefinition.model_validate({"name": "x", "steps": []})
