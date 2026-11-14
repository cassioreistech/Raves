from typer.testing import CliRunner

from raves.core import database
from raves.core.dispatcher import execute_natural_command
from raves.engine.observer import ContextObserver
from raves.main import app


def test_insights_profile_vazio() -> None:
    result = CliRunner().invoke(app, ["insights", "profile"])
    assert result.exit_code == 0
    assert "Nenhum interesse ainda" in result.stdout
    assert "Nenhuma rotina" in result.stdout


def test_insights_profile_mostra_interesses_e_horarios(mocker) -> None:
    mocker.patch.object(
        ContextObserver,
        "read_foreground",
        return_value=("chrome.exe", "Lo-Fi Beats - YouTube"),
    )
    ContextObserver().capture_once()
    result = CliRunner().invoke(app, ["insights", "profile"])
    assert result.exit_code == 0
    assert "lo-fi" in result.stdout or "musica" in result.stdout
    assert "evento(s) de atividade" in result.stdout


def test_insights_suggest_exibe_recomendacoes() -> None:
    database.upsert_interest("musica", "lofi")
    result = CliRunner().invoke(app, ["insights", "suggest"])
    assert result.exit_code == 0
    assert "lofi" in result.stdout


def test_insights_forget_apaga_tudo() -> None:
    database.upsert_interest("musica", "lofi")
    database.upsert_routine("dow=0;bucket=manha", ["abrir calc"], 0.9, 4)
    result = CliRunner().invoke(app, ["insights", "forget"])
    assert result.exit_code == 0
    assert database.get_interest_profile() == []
    assert database.get_routines() == []


def test_dispatcher_pedidos_de_insight() -> None:
    for phrase in ("o que voce aprendeu", "me de uma dica", "sugestoes", "meu perfil"):
        results = execute_natural_command(phrase, apply=False)
        assert results
        assert all(item.ok for item in results)
        assert any("padrão" in item.message for item in results)


def test_insights_nao_viram_alvo_de_repetir() -> None:
    execute_natural_command("sugestoes", apply=False)
    assert database.get_last_successful_command() is None


def test_voice_listen_modo_texto() -> None:
    result = CliRunner().invoke(app, ["voice", "listen"], input="sair\n")
    assert result.exit_code == 0
    assert "Modo texto" in result.stdout
    assert "Até logo" in result.stdout
