from raves.engine import tts


def test_neural_speaker_fallback_quando_modelo_ausente(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(tts, "PIPER_MODEL_DIR", tmp_path)
    speaker = tts.NeuralSpeaker()
    assert speaker.is_available() is False
    assert speaker.synthesize("ola") is None
    assert speaker.speak("ola") is False


def test_neural_speaker_synthesize_com_modelo_mockado(tmp_path, mocker) -> None:
    model_dir = tmp_path
    (model_dir / "pt_BR-faber-medium.onnx").write_bytes(b"x")
    (model_dir / "pt_BR-faber-medium.onnx.json").write_text("{}", encoding="utf-8")
    mocker.patch.object(tts, "PIPER_MODEL_DIR", model_dir)

    fake_voice = mocker.MagicMock()
    mocker.patch("piper.PiperVoice.load", return_value=fake_voice)

    speaker = tts.NeuralSpeaker()
    assert speaker.is_available() is True
    # synthesize escreve wav e le de volta; mock wave.open

    fake_wav = mocker.MagicMock()
    fake_wav.getnframes.return_value = 4
    fake_wav.getframerate.return_value = 22050
    fake_wav.readframes.return_value = b"\x00" * 8
    mocker.patch("wave.open", return_value=fake_wav)
    fake_wav.__enter__ = lambda self: fake_wav
    fake_wav.__exit__ = lambda self, *a: None

    result = speaker.synthesize("ola")
    assert result is not None
    audio, rate = result
    assert rate == 22050
    assert audio.size == 4


def test_neural_speaker_speak_usa_sd_play_e_stop(mocker) -> None:
    speaker = tts.NeuralSpeaker()
    mocker.patch.object(speaker, "is_available", return_value=True)
    import numpy as np

    mocker.patch.object(
        speaker, "synthesize", return_value=(np.array([0, 0], dtype=np.int16), 22050)
    )
    sd = mocker.patch("sounddevice.play")
    wait = mocker.patch("sounddevice.wait")
    assert speaker.speak("ola") is True
    sd.assert_called_once()
    wait.assert_called_once()


def test_tts_engine_fallback_pyttsx3_quando_winrt_falha(mocker) -> None:
    engine = tts.TTSEngine(gender="feminina")
    mocker.patch.object(engine, "_speak_winrt", return_value=False)
    mocker.patch.object(engine, "_speak_piper", side_effect=Exception("no model"))
    pyttsx = mocker.patch.object(engine, "_speak_pyttsx3")
    engine.speak("teste")
    pyttsx.assert_called_once_with("teste")


def test_tts_engine_aplica_prosody(mocker) -> None:
    engine = tts.TTSEngine(gender="feminina")
    mocker.patch.object(engine, "_speak_winrt", return_value=True)
    engine.speak("abra o VS Code")
    # _speak_winrt recebe o texto processado (com prosodia aplicada)
    args = engine._speak_winrt.call_args[0][0]
    assert "vê ésse côde" in args


def test_get_set_gender() -> None:

    tts.set_gender("masculina")
    assert tts.get_gender() == "masculina"
    tts.set_gender("feminina")
    assert tts.get_gender() == "feminina"
    try:
        tts.set_gender("alien")
    except ValueError:
        pass
    else:
        raise AssertionError("set_gender deveria rejeitar genero invalido")
