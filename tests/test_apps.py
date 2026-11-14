from typer.testing import CliRunner

from raves.core import database, dispatcher
from raves.core.config import SecuritySettings
from raves.engine import app_indexer
from raves.engine.windows_api import launch_app
from raves.main import app


def test_apps_sync_com_spinner(mocker) -> None:
    scan = mocker.patch("raves.commands.apps.scan_and_index_windows_apps", return_value=42)
    result = CliRunner().invoke(app, ["apps", "sync"])
    assert result.exit_code == 0
    assert "42 aplicativo(s) indexado(s)" in result.stdout
    scan.assert_called_once()


def test_apps_list_com_filter() -> None:
    database.upsert_apps(
        [
            ("google chrome", r"C:\a\chrome.exe", "start_menu_all"),
            ("notepad", r"C:\b\notepad.exe", "app_paths_hklm"),
        ]
    )
    result = CliRunner().invoke(app, ["apps", "list", "--filter", "chrome"])
    assert result.exit_code == 0
    assert "google chrome" in result.stdout
    assert "notepad" not in result.stdout


def test_apps_list_vazio() -> None:
    result = CliRunner().invoke(app, ["apps", "list"])
    assert result.exit_code == 0
    assert "Nenhum aplicativo indexado" in result.stdout


def test_ensure_app_index_roda_uma_vez_quando_vazio(monkeypatch, mocker) -> None:
    monkeypatch.delenv("RAVES_SKIP_APP_INDEX")
    dispatcher._index_checked = False
    scan = mocker.patch("raves.engine.app_indexer.scan_and_index_windows_apps", return_value=7)

    assert dispatcher.ensure_app_index() == 7
    assert dispatcher.ensure_app_index() == 0  # guarda de "uma vez"
    scan.assert_called_once()


def test_ensure_app_index_nao_varre_com_tabela_populada(monkeypatch, mocker) -> None:
    monkeypatch.delenv("RAVES_SKIP_APP_INDEX")
    dispatcher._index_checked = False
    database.upsert_apps([("notepad", r"C:\b\notepad.exe", "app_paths_hklm")])
    scan = mocker.patch("raves.engine.app_indexer.scan_and_index_windows_apps", return_value=7)

    assert dispatcher.ensure_app_index() == 0
    scan.assert_not_called()


def test_normalizacao_e_aliases() -> None:
    assert app_indexer._normalize_name("Google Chrome") == "google chrome"
    assert app_indexer._normalize_name("Foo  (x64)") == "foo"
    assert app_indexer._aliases("google chrome") == ["google chrome", "googlechrome"]
    assert app_indexer._aliases("chrome") == ["chrome"]


def test_clean_exe_path_remove_aspas_e_argumentos() -> None:
    assert (
        app_indexer._clean_exe_path(r'"C:\Program Files\Foo\foo.exe" --flag')
        == r"C:\Program Files\Foo\foo.exe"
    )
    assert (
        app_indexer._clean_exe_path(r"C:\Program Files\Foo\foo.exe /S")
        == r"C:\Program Files\Foo\foo.exe"
    )
    assert app_indexer._clean_exe_path("") is None


def test_scan_ignora_desinstaladores(tmp_path, mocker) -> None:
    programs = tmp_path / "Programs"
    (programs / "Sub").mkdir(parents=True)
    (programs / "Google Chrome.lnk").write_bytes(b"x")
    (programs / "Sub" / "Notepad.lnk").write_bytes(b"x")
    (programs / "Uninstall Foo.lnk").write_bytes(b"x")
    (programs / "Remover Bar.lnk").write_bytes(b"x")

    mocker.patch.object(app_indexer, "_start_menu_dirs", return_value=[(programs, "test")])
    mocker.patch.object(app_indexer, "_read_app_paths", return_value=[])

    count = app_indexer.scan_and_index_windows_apps()
    names = {row["name"] for row in database.get_apps()}
    assert count == 3  # "google chrome" + alias "googlechrome" + "notepad"
    assert "google chrome" in names
    assert "googlechrome" in names
    assert "notepad" in names
    assert not any("uninstall" in name or "remover" in name for name in names)


def test_launch_app_abre_lnk_por_caminho_fixo(tmp_path, mocker) -> None:
    shortcut = tmp_path / "Foo.lnk"
    shortcut.write_bytes(b"x")
    starter = mocker.patch("os.startfile", create=True)

    policy = SecuritySettings(allowed_apps=["foo.lnk"])
    assert launch_app(str(shortcut), dry_run=False, policy=policy) is True
    starter.assert_called_once_with(str(shortcut))
