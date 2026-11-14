import pytest
from typer.testing import CliRunner

from winbot.core import dispatcher


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture(autouse=True)
def _isolated_winbot_db(tmp_path, monkeypatch) -> None:
    """Nenhum teste escreve em ~/.winbot/winbot.db nem varre o Windows real."""
    monkeypatch.setenv("WINBOT_DB_PATH", str(tmp_path / "winbot.db"))
    monkeypatch.setenv("WINBOT_SKIP_APP_INDEX", "1")
    monkeypatch.setattr(dispatcher, "_index_checked", False)
