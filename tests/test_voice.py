from typer.testing import CliRunner

from winbot.engine import audio_pipeline
from winbot.main import app


def test_voice_calibrate_com_audio_mockado(mocker) -> None:
    mocker.patch.object(
        audio_pipeline.ResilientAudioCapture,
        "start",
        lambda self: setattr(self, "_running", True),
    )
    mocker.patch.object(
        audio_pipeline.ResilientAudioCapture, "calibrate", lambda self, duration=0.5: 0.01
    )
    mocker.patch.object(
        audio_pipeline.ResilientAudioCapture,
        "record_utterance",
        lambda self, timeout=3.0: b"\x00" * 100,
    )
    mocker.patch.object(audio_pipeline.ResilientAudioCapture, "stop", lambda self: None)

    result = CliRunner().invoke(app, ["voice", "calibrate"])
    assert result.exit_code == 0
    assert "Calibração concluída" in result.stdout
    assert "Initial prompt" in result.stdout


def test_voice_listen_encerra_limpo() -> None:
    result = CliRunner().invoke(app, ["voice", "listen"], input="sair\n")
    assert result.exit_code == 0
    assert "Até logo" in result.stdout
