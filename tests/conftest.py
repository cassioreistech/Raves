import os

# Headless Qt para os testes de UI (deve vir ANTES de importar PySide6).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from typer.testing import CliRunner

from raves.core import dispatcher, session


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture(autouse=True)
def _isolated_raves_db(tmp_path, monkeypatch) -> None:
    """Nenhum teste escreve em ~/.raves/raves.db nem varre o Windows real."""
    monkeypatch.setenv("RAVES_DB_PATH", str(tmp_path / "raves.db"))
    monkeypatch.setenv("RAVES_SKIP_APP_INDEX", "1")
    # Telemetria passiva nunca deve rodar de verdade dentro da suite.
    monkeypatch.setenv("RAVES_OBSERVER_DISABLED", "1")
    # Cerebro hibrido: nao tentar Ollama durante os testes.
    monkeypatch.setenv("RAVES_DISABLE_LOCAL_BRAIN", "1")
    # Voz: nao abrir microfone/Whisper durante os testes.
    monkeypatch.setenv("RAVES_DISABLE_ASR", "1")
    monkeypatch.setattr(dispatcher, "_index_checked", False)
    session.get_session().reset()
