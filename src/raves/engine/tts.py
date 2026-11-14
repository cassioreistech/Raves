"""TTS offline premium (Etapa de Voz Natural).

Prioridade: Piper (neural, pt-BR masculino) quando disponível → WinRT
SpeechSynthesis (Maria/Daniel, OneCore, offline) → pyttsx3 (SAPI5) como
fallback final. Tudo 100% local, sem nuvem.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

from raves.core import database
from raves.core.logger import logger

PIPER_MODEL_DIR = Path.home() / ".raves" / "voices"
PIPER_MODEL_NAME = "pt_BR-faber-medium"


def _gender() -> str:
    value = database.get_voice_profile("tts_gender")
    return value if value in {"masculina", "feminina"} else "feminina"


def _winrt_voice_for(gender: str) -> Any:
    try:
        from winrt.windows.media.speechsynthesis import SpeechSynthesizer
    except ImportError:
        return None
    try:
        voices = SpeechSynthesizer.all_voices
    except Exception:
        return None
    target_gender = 0 if gender == "masculina" else 1  # 0=Male, 1=Female
    for voice in voices:
        try:
            if "pt" in (voice.language or "").lower() and int(voice.gender) == target_gender:
                return voice
        except Exception:
            continue
    # Fallback: qualquer voz pt-BR.
    for voice in voices:
        try:
            if "pt" in (voice.language or "").lower():
                return voice
        except Exception:
            continue
    return None


def _piper_model_path() -> Path | None:
    model = PIPER_MODEL_DIR / f"{PIPER_MODEL_NAME}.onnx"
    config = PIPER_MODEL_DIR / f"{PIPER_MODEL_NAME}.onnx.json"
    if model.is_file() and config.is_file():
        return model
    return None


def _download_piper_model() -> Path | None:
    try:
        PIPER_MODEL_DIR.mkdir(parents=True, exist_ok=True)
        from piper import download_voices

        download_voices.download_voice(PIPER_MODEL_NAME, PIPER_MODEL_DIR)
        model = PIPER_MODEL_DIR / f"{PIPER_MODEL_NAME}.onnx"
        return model if model.is_file() else None
    except Exception as exc:
        logger.debug(f"tts: falha ao baixar modelo Piper ({exc})")
        return None


class NeuralSpeaker:
    """Sintetizador neural Piper (pt-BR) com reprodução via sounddevice.

    Sintetiza em memória (numpy int16) e reproduz com ``sd.play``, permitindo
    barge-in instantâneo via ``sd.stop()``. Usado como backend premium para a
    voz masculina quando o modelo está disponível.
    """

    def __init__(self, model_name: str = PIPER_MODEL_NAME) -> None:
        self.model_name = model_name
        self.model_path = PIPER_MODEL_DIR / f"{model_name}.onnx"

    def is_available(self) -> bool:
        config = PIPER_MODEL_DIR / f"{self.model_name}.onnx.json"
        return self.model_path.is_file() and config.is_file()

    def synthesize(self, text: str) -> tuple[Any, int] | None:
        """Retorna (numpy array int16, sample_rate) ou None em falha."""
        if not self.is_available():
            return None
        try:
            import wave

            import numpy as np
            from piper import PiperVoice

            voice = PiperVoice.load(self.model_path)
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = tmp.name
            try:
                with wave.open(tmp_path, "wb") as wav_file:
                    voice.synthesize_wav(text, wav_file)
                with wave.open(tmp_path, "rb") as wav_file:
                    rate = wav_file.getframerate()
                    frames = wav_file.readframes(wav_file.getnframes())
                    audio = np.frombuffer(frames, dtype=np.int16).copy()
                return audio, rate
            finally:
                with contextlib.suppress(OSError):
                    os.unlink(tmp_path)
        except Exception as exc:
            logger.debug(f"neural_speaker: falha na síntese ({exc})")
            return None

    def speak(self, text: str) -> bool:
        if not text or not text.strip():
            return False
        result = self.synthesize(text)
        if result is None:
            return False
        audio, rate = result
        if audio is None or audio.size == 0:
            return False
        try:
            import sounddevice as sd

            sd.play(audio, samplerate=rate)
            sd.wait()
            return True
        except Exception as exc:
            logger.debug(f"neural_speaker: falha na reprodução ({exc})")
            return False

    def stop(self) -> None:
        try:
            import sounddevice as sd

            sd.stop()
        except Exception:
            pass


class TTSEngine:
    """TTS offline com voz masculina/feminina e barge-in cooperativo."""

    def __init__(self, gender: str | None = None) -> None:
        self.gender = gender or _gender()
        self._playing = threading.Event()
        self._stop_requested = threading.Event()
        self._lock = threading.Lock()

    @property
    def is_playing(self) -> bool:
        return self._playing.is_set()

    def speak(self, text: str) -> None:
        if not text or not text.strip():
            return
        from raves.engine.prosody import prepare_speech_text

        text = prepare_speech_text(text)
        if not text:
            return
        self._playing.set()
        self._stop_requested.clear()
        try:
            if self.gender == "masculina":
                speaker = NeuralSpeaker()
                if speaker.is_available() and speaker.speak(text):
                    return
                model_path = _piper_model_path()
                if model_path is not None:
                    self._speak_piper(text, model_path)
                    return
            # WinRT (Maria/Daniel) — offline, melhor qualidade disponível.
            if self._speak_winrt(text):
                return
            self._speak_pyttsx3(text)
        except Exception as exc:
            logger.debug(f"tts: falha ({exc})")
            with contextlib.suppress(Exception):
                self._speak_pyttsx3(text)
        finally:
            self._playing.clear()

    def stop(self) -> None:
        self._stop_requested.set()
        try:
            import winsound

            winsound.PlaySound(None, winsound.SND_PURGE)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Backends
    # ------------------------------------------------------------------

    def _speak_winrt(self, text: str) -> bool:
        try:
            import winsound

            from winrt.windows.media.speechsynthesis import SpeechSynthesizer
            from winrt.windows.storage.streams import DataReader
        except ImportError:
            return False
        try:
            synth = SpeechSynthesizer()
            voice = _winrt_voice_for(self.gender)
            if voice is not None:
                synth.voice = voice
            stream = synth.synthesize_text_to_stream_async(text).get()
            size = int(stream.size)
            if size <= 0:
                return False
            reader = DataReader(stream)
            reader.load_async(size).get()
            buffer = bytearray(size)
            reader.read_bytes(buffer)
            data = bytes(buffer)
            reader.close()
            stream.close()
            if self._stop_requested.is_set():
                return True
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp.write(data)
                tmp_path = tmp.name
            try:
                winsound.PlaySound(tmp_path, winsound.SND_FILENAME)
            finally:
                with contextlib.suppress(OSError):
                    os.unlink(tmp_path)
            return True
        except Exception as exc:
            logger.debug(f"tts: winrt falhou ({exc})")
            return False

    def _speak_piper(self, text: str, model_path: Path) -> None:
        import wave
        import winsound

        from piper import PiperVoice

        voice = PiperVoice.load(model_path)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            with wave.open(tmp_path, "wb") as wav_file:
                voice.synthesize_wav(text, wav_file)
            if not self._stop_requested.is_set():
                winsound.PlaySound(tmp_path, winsound.SND_FILENAME)
        finally:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)

    def _speak_pyttsx3(self, text: str) -> None:
        import pyttsx3

        engine = pyttsx3.init()
        try:
            engine.setProperty("rate", 170)
            engine.setProperty("volume", 1.0)
            # seleciona voz pt-BR por gênero quando possível
            raw_voices = engine.getProperty("voices")
            voices = list(raw_voices) if isinstance(raw_voices, (list, tuple)) else []
            chosen = None
            for voice in voices:
                name = (voice.name or "").lower()
                langs = " ".join(getattr(voice, "languages", []) or []).lower()
                if "pt" in langs or "brazil" in name or "portuguese" in name:
                    if self.gender == "feminina" and (
                        "maria" in name or "zira" in name or "female" in name
                    ):
                        chosen = voice
                        break
                    if self.gender == "masculina" and ("david" in name or "male" in name):
                        chosen = voice
                        break
            if chosen is None:
                # fallback: primeira voz pt-BR disponível
                for voice in voices:
                    name = (voice.name or "").lower()
                    langs = " ".join(getattr(voice, "languages", []) or []).lower()
                    if "pt" in langs or "brazil" in name or "portuguese" in name:
                        chosen = voice
                        break
            if chosen is not None:
                engine.setProperty("voice", chosen.id)
        except Exception:
            pass
        engine.say(text)
        engine.runAndWait()
        with contextlib.suppress(Exception):
            engine.stop()


def get_gender() -> str:
    value = database.get_voice_profile("tts_gender")
    return value if value in {"masculina", "feminina"} else "feminina"


def set_gender(gender: str) -> None:
    if gender not in {"masculina", "feminina"}:
        raise ValueError("gênero inválido (use masculina ou feminina)")
    database.set_voice_profile("tts_gender", gender)


def speak_text(text: str, gender: str | None = None) -> None:
    """Fala um texto via TTSEngine em background (best-effort)."""
    if not text or not text.strip():
        return

    def _worker() -> None:
        with contextlib.suppress(Exception):
            TTSEngine(gender=gender or get_gender()).speak(text)

    threading.Thread(target=_worker, name="raves-tts", daemon=True).start()


def setup_tts_model() -> tuple[bool, str]:
    """Baixa o modelo Piper pt-BR (masculino, neural) para uso offline."""
    model = _download_piper_model()
    if model is not None:
        return True, f"Modelo Piper disponível em {model}"
    return False, "Falha ao baixar o modelo Piper (verifique a rede)."
