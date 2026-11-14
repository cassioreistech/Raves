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
    # Telemetria passiva nunca deve rodar de verdade dentro da suite.
    monkeypatch.setenv("WINBOT_OBSERVER_DISABLED", "1")
    # Cerebro hibrido: nao tentar Ollama durante os testes.
    monkeypatch.setenv("WINBOT_DISABLE_LOCAL_BRAIN", "1")
    monkeypatch.setattr(dispatcher, "_index_checked", False)
