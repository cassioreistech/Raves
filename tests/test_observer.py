from datetime import datetime

from winbot.core import database
from winbot.engine import observer


def test_classifica_musica_com_alias_curto() -> None:
    category, keywords = observer.classify("chrome.exe", "Lo-Fi Beats - YouTube")
    assert category == "musica"
    assert "lo-fi" in keywords


def test_classifica_desenvolvimento_pesquisa_e_outros() -> None:
    assert observer.classify("Code.exe", "main.py - Visual Studio Code")[0] == "desenvolvimento"
    assert observer.classify("msedge.exe", "como fazer X - Google")[0] == "pesquisa"
    assert observer.classify("app.exe", "Janela qualquer 123")[0] == "outros"


def test_spotify_e_spotify_musica() -> None:
    assert observer.classify("Spotify.exe", "Rock Clássico - Spotify")[0] == "musica"
    assert observer.classify("chrome.exe", "Sertanejo playlist")[0] == "musica"


def test_hour_bucket_e_contexto_local() -> None:
    assert database.hour_bucket_for(8) == "manha"
    assert database.hour_bucket_for(14) == "tarde"
    assert database.hour_bucket_for(20) == "noite"
    assert database.hour_bucket_for(2) == "madrugada"
    iso = "2026-11-09T13:00:00+00:00"
    expected = datetime.fromisoformat(iso).astimezone()
    dow, bucket = database.parse_local_context(iso)
    assert dow == expected.weekday()
    assert bucket == database.hour_bucket_for(expected.hour)


def test_capture_once_grava_e_nao_duplica(mocker) -> None:
    mocker.patch.object(
        observer.ContextObserver,
        "read_foreground",
        return_value=("chrome.exe", "Lo-Fi Beats - YouTube"),
    )
    obs = observer.ContextObserver()
    event = obs.capture_once()
    assert event is not None
    assert event["category"] == "musica"
    assert obs.capture_once() is None
    assert database.count_activity_events() == 1
    assert database.get_interest_profile()


def test_capture_once_ignora_janela_vazia(mocker) -> None:
    mocker.patch.object(observer.ContextObserver, "read_foreground", return_value=None)
    assert observer.ContextObserver().capture_once() is None
    assert database.count_activity_events() == 0


def test_start_stop_com_event_limpo(monkeypatch, mocker) -> None:
    monkeypatch.delenv("WINBOT_OBSERVER_DISABLED")
    mocker.patch.object(observer.ContextObserver, "capture_once", return_value=None)
    obs = observer.ContextObserver()
    obs.start_background_watch(interval_seconds=5)
    assert obs.running is True
    obs.stop()
    assert obs.running is False


def test_observer_desligado_por_env(monkeypatch) -> None:
    monkeypatch.setenv("WINBOT_OBSERVER_DISABLED", "1")
    obs = observer.ContextObserver()
    obs.start_background_watch()
    assert obs.running is False
