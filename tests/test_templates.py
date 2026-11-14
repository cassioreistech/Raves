from pathlib import Path

from winbot.core import templates


def test_install_default_templates_quando_vazio(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(templates, "Path", Path)
    # Redireciona Path.home() para tmp_path via monkeypatch do module-level? Simpler:
    import winbot.core.templates as t

    original_home = Path.home
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    try:
        assert t.install_default_templates() == 4
        directory = tmp_path / ".winbot" / "workflows"
        assert (directory / "modo_foco.yaml").exists()
        assert (directory / "organizar_downloads.yaml").exists()
    finally:
        monkeypatch.setattr(Path, "home", original_home)


def test_install_default_templates_nao_sobrescreve(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    directory = tmp_path / ".winbot" / "workflows"
    directory.mkdir(parents=True)
    (directory / "custom.yaml").write_text("name: x\nsteps: []\n", encoding="utf-8")
    assert templates.install_default_templates() == 0
    assert not (directory / "modo_foco.yaml").exists()
