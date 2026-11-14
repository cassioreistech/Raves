"""Configuração validada e schema de workflows (Pydantic v2 + YAML).

Precedência da config: defaults empacotados -> %LOCALAPPDATA%\\WinBot\\settings.yaml.
Nenhum segredo deve viver em arquivo versionado.
"""

from __future__ import annotations

import os
from importlib.resources import files
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

_DEFAULTS = files("winbot").joinpath("assets", "settings.defaults.yaml")


class GeneralSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dry_run: bool = True
    log_level: str = "INFO"


class PathSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace: str | None = None


class SecuritySettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allow_shell: bool = False
    allowed_executables: list[str] = Field(
        default_factory=lambda: ["powershell.exe", "pwsh.exe", "cmd.exe"]
    )
    allowed_apps: list[str] = Field(
        default_factory=lambda: ["notepad.exe", "calc.exe", "explorer.exe"]
    )
    deny_processes: list[str] = Field(
        default_factory=lambda: [
            "system",
            "smss.exe",
            "csrss.exe",
            "wininit.exe",
            "services.exe",
            "lsass.exe",
            "winlogon.exe",
            "svchost.exe",
            "explorer.exe",
        ]
    )
    command_timeout_s: int = 30
    deny_patterns: list[str] = Field(default_factory=list)


class LicensingSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Desligado em desenvolvimento; ligar apenas no build de distribuição.
    enabled: bool = False
    trial_days: int = 14
    grace_days: int = 7


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    general: GeneralSettings = Field(default_factory=GeneralSettings)
    paths: PathSettings = Field(default_factory=PathSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    licensing: LicensingSettings = Field(default_factory=LicensingSettings)

    def workspace_path(self) -> Path:
        return Path(self.paths.workspace) if self.paths.workspace else Path.home() / "WinBot"


def user_config_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "WinBot"
    return base / "settings.yaml"


def _read_yaml(source: Any) -> dict[str, Any]:
    with source.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Configuração inválida em {source}: esperado mapeamento YAML")
    return data


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def load_settings(path: Path | None = None) -> Settings:
    """Carrega os defaults empacotados e aplica o override do usuário, se existir."""
    data = _read_yaml(_DEFAULTS)
    override = path if path is not None else user_config_path()
    if override.exists():
        data = _merge(data, _read_yaml(override))
    return Settings.model_validate(data)


def create_user_config(path: Path | None = None) -> Path:
    """Materializa o template de configuração do cliente (idempotente)."""
    target = path if path is not None else user_config_path()
    if target.exists():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    with _DEFAULTS.open("r", encoding="utf-8") as handle:
        target.write_text(handle.read(), encoding="utf-8")
    return target


WorkflowAction = Literal[
    "powershell",
    "launch_app",
    "kill_process",
    "focus_window",
    "wait",
    "gui_click",
    "gui_click_image",
    "gui_type",
    "gui_hotkey",
    "clean_temp",
    "uia_click",
    "uia_fill",
    "wait_window",
    "ocr_click",
]
MAX_WAIT_SECONDS = 60.0


class WorkflowStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., description="Nome amigável da etapa")
    action: WorkflowAction
    params: dict[str, Any] = Field(default_factory=dict)
    continue_on_error: bool = False

    @model_validator(mode="after")
    def _payload(self) -> WorkflowStep:
        required = {
            "powershell": "command",
            "launch_app": "target",
            "kill_process": "name",
            "focus_window": "title",
            "gui_click_image": "image",
            "gui_type": "text",
            "gui_hotkey": "keys",
        }
        if self.action in required and not self.params.get(required[self.action]):
            raise ValueError(f"ação '{self.action}' exige params.{required[self.action]}")
        if self.action == "wait":
            seconds = float(self.params.get("seconds", 1))
            if not 0 <= seconds <= MAX_WAIT_SECONDS:
                raise ValueError(f"params.seconds deve estar entre 0 e {MAX_WAIT_SECONDS}")
        if self.action == "gui_click":
            x, y = self.params.get("x"), self.params.get("y")
            if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
                raise ValueError("ação 'gui_click' exige params.x e params.y numéricos")
        if self.action == "gui_hotkey":
            keys = self.params.get("keys")
            if not isinstance(keys, list) or not keys:
                raise ValueError("ação 'gui_hotkey' exige params.keys (lista não vazia)")
        if self.action in {"uia_click", "uia_fill"} and not self.params.get("control"):
            raise ValueError(f"ação '{self.action}' exige params.control")
        if self.action == "uia_fill":
            if not self.params.get("window"):
                raise ValueError("ação 'uia_fill' exige params.window")
            if not self.params.get("text"):
                raise ValueError("ação 'uia_fill' exige params.text não vazio")
        if self.action == "uia_click" and "window" not in self.params:
            self.params["window"] = ""
        if self.action == "wait_window":
            if not self.params.get("title"):
                raise ValueError("ação 'wait_window' exige params.title")
            timeout = self.params.get("timeout", 15)
            if not isinstance(timeout, (int, float)) or not 1 <= timeout <= 120:
                raise ValueError("params.timeout deve estar entre 1 e 120")
        if self.action == "ocr_click" and not self.params.get("text"):
            raise ValueError("ação 'ocr_click' exige params.text")
        return self


class WorkflowDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    steps: list[WorkflowStep] = Field(min_length=1)
