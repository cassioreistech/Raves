import json
from unittest.mock import MagicMock, patch

from raves.ai.local_brain import LocalBrain


def test_is_available_cache_e_offline(monkeypatch) -> None:
    monkeypatch.delenv("RAVES_DISABLE_LOCAL_BRAIN", raising=False)
    brain = LocalBrain()
    with patch("urllib.request.urlopen", side_effect=OSError("offline")):
        assert brain.is_available() is False
        # Cache de 60s: segunda chamada nao tenta de novo.
        with patch("urllib.request.urlopen") as mock_open:
            assert brain.is_available() is False
            mock_open.assert_not_called()


def test_is_available_respeita_env_disable(monkeypatch) -> None:
    monkeypatch.setenv("RAVES_DISABLE_LOCAL_BRAIN", "1")
    brain = LocalBrain()
    assert brain.is_available() is False


def test_ask_retorna_action_quando_llm_responde_action(monkeypatch) -> None:
    monkeypatch.delenv("RAVES_DISABLE_LOCAL_BRAIN", raising=False)
    brain = LocalBrain()
    # Forca disponivel.
    brain._available_cache = (True, __import__("time").monotonic())
    payload = {"response": "ACTION: abrir calc"}
    fake = MagicMock()
    fake.read.return_value = json.dumps(payload).encode()
    fake.__enter__ = lambda self: fake
    fake.__exit__ = lambda self, *a: None
    with patch("urllib.request.urlopen", return_value=fake):
        result = brain.ask("abra a calculadora")
    assert result["action"] == "abrir calc"
    assert result["text"] == ""


def test_ask_retorna_texto_conversacional(monkeypatch) -> None:
    monkeypatch.delenv("RAVES_DISABLE_LOCAL_BRAIN", raising=False)
    brain = LocalBrain()
    brain._available_cache = (True, __import__("time").monotonic())
    payload = {"response": "Olá! Posso ajudar com automações."}
    fake = MagicMock()
    fake.read.return_value = json.dumps(payload).encode()
    fake.__enter__ = lambda self: fake
    fake.__exit__ = lambda self, *a: None
    with patch("urllib.request.urlopen", return_value=fake):
        result = brain.ask("oi")
    assert result["action"] is None
    assert "Olá" in result["text"]


def test_ask_offline_retorna_vazio() -> None:
    brain = LocalBrain()
    brain._available_cache = (False, __import__("time").monotonic())
    result = brain.ask("qualquer coisa")
    assert result == {"text": "", "action": None}


def test_ask_inclui_clipboard_quando_mencionado(monkeypatch) -> None:
    monkeypatch.delenv("RAVES_DISABLE_LOCAL_BRAIN", raising=False)
    brain = LocalBrain()
    brain._available_cache = (True, __import__("time").monotonic())
    captured: dict[str, str] = {}

    def fake_urlopen(request, timeout=30.0):
        captured["body"] = request.data.decode()
        fake = MagicMock()
        fake.read.return_value = json.dumps({"response": "resumo"}).encode()
        fake.__enter__ = lambda self: fake
        fake.__exit__ = lambda self, *a: None
        return fake

    monkeypatch.setattr("pyperclip.paste", lambda: "texto copiado secreto")
    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        brain.ask("resuma a area de transferencia")
    assert "texto copiado secreto" in captured["body"]


def test_keep_alive_dois_minutos_no_payload(monkeypatch) -> None:
    monkeypatch.delenv("RAVES_DISABLE_LOCAL_BRAIN", raising=False)
    brain = LocalBrain()
    brain._available_cache = (True, __import__("time").monotonic())
    captured: dict[str, str] = {}

    def fake_urlopen(request, timeout=30.0):
        captured["body"] = request.data.decode()
        fake = MagicMock()
        fake.read.return_value = json.dumps({"response": "ok"}).encode()
        fake.__enter__ = lambda self: fake
        fake.__exit__ = lambda self, *a: None
        return fake

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        brain.ask("oi")
    payload = json.loads(captured["body"])
    assert payload["keep_alive"] == "90s"
