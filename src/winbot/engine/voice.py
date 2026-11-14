"""Motor de voz offline (Etapa 3): STT (faster-whisper) + TTS (pyttsx3) + barge-in.

Tudo roda em threads dedicadas. Nenhuma chamada de rede: o modelo Whisper é
carregado do cache local (download manual uma vez, ver README).
"""

from __future__ import annotations

import contextlib
import difflib
import queue
import threading
import time
from collections.abc import Callable
from typing import Any

from winbot.core import database
from winbot.core.logger import logger
from winbot.engine.audio_pipeline import ResilientAudioCapture

try:
    from faster_whisper import WhisperModel
except ImportError:  # pragma: no cover - dependencia opcional em runtime
    WhisperModel = None  # type: ignore[assignment,misc]


class VoiceEngine:
    def __init__(
        self,
        model_size: str = "tiny",
        device: str = "cpu",
        compute_type: str = "int8",
    ) -> None:
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self._model: Any = None
        self._model_lock = threading.Lock()
        self._audio = ResilientAudioCapture()
        self._tts_queue: queue.Queue[str] = queue.Queue()
        self._tts_engine: Any = None
        self._speaking = threading.Event()
        self._interrupt = threading.Event()
        self._stop = threading.Event()
        self._tts_thread: threading.Thread | None = None
        self._monitor_thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._audio is None:
            return
        self._audio.start()
        try:
            self._audio.calibrate()
        except Exception as exc:
            logger.debug(f"voice: calibração ignorada ({exc})")
        self._stop.clear()
        self._tts_thread = threading.Thread(target=self._tts_worker, name="winbot-tts", daemon=True)
        self._tts_thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._audio.stop()
        self._interrupt.set()
        if self._tts_engine is not None:
            with contextlib.suppress(Exception):
                self._tts_engine.stop()
        if self._tts_thread is not None:
            self._tts_thread.join(timeout=2.0)
            self._tts_thread = None

    @property
    def speaking(self) -> bool:
        return self._speaking.is_set()

    # ------------------------------------------------------------------
    # STT
    # ------------------------------------------------------------------

    def _get_model(self) -> Any:
        with self._model_lock:
            if self._model is not None:
                return self._model
            if WhisperModel is None:
                return None
            try:
                self._model = WhisperModel(
                    self.model_size,
                    device=self.device,
                    compute_type=self.compute_type,
                    local_files_only=True,
                )
                return self._model
            except Exception as exc:
                logger.warning(f"voice: falha ao carregar Whisper '{self.model_size}': {exc}")
                return None

    def build_initial_prompt(self) -> str:
        parts = [
            "Comandos WinBot: abrir, fechar, focar, digitar, atalho, limpar temp, "
            "esperar, repetir, historico, sugestoes, meu perfil, "
            "aprender palavra, memorizar termo.",
        ]
        try:
            apps = database.get_apps()
            names = [str(item["name"]) for item in apps[:40]]
            if names:
                parts.append("Aplicativos: " + ", ".join(names) + ".")
        except Exception:
            pass
        vocab = database.get_custom_vocab()
        if vocab:
            parts.append("Termos técnicos: " + ", ".join(vocab) + ".")
        corrections = database.get_speech_corrections()
        heard = [str(item["heard_phrase"]) for item in corrections[:20]]
        if heard:
            parts.append("Pronúncias aprendidas: " + ", ".join(heard) + ".")
        return " ".join(parts)

    def transcribe(self, pcm_bytes: bytes) -> str:
        model = self._get_model()
        if model is None or not pcm_bytes:
            return ""
        try:
            import numpy as np

            audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype("float32") / 32768.0
            prompt = self.build_initial_prompt()
            segments, _info = model.transcribe(
                audio,
                language="pt",
                initial_prompt=prompt,
                beam_size=5,
                temperature=0.0,
                vad_filter=True,
            )
            return " ".join(segment.text for segment in segments).strip()
        except Exception as exc:
            logger.warning(f"voice: transcrição falhou: {exc}")
            return ""

    def match_command(self, heard: str) -> str | None:
        """Fuzzy match contra comandos/apps conhecidos (similarity >= 0.75)."""
        heard = heard.strip().lower()
        if not heard:
            return None
        known: list[str] = [
            "abrir calc",
            "fechar calc",
            "repetir",
            "repetir ultimo",
            "historico",
            "ultimos comandos",
            "sugestoes",
            "meu perfil",
            "me de uma dica",
            "o que voce aprendeu",
            "limpar temp",
        ]
        try:
            for app in database.get_apps():
                name = str(app["name"])
                known.append(f"abrir {name}")
                known.append(f"fechar {name}")
        except Exception:
            pass
        matches = difflib.get_close_matches(heard, known, n=1, cutoff=0.75)
        if not matches:
            return None
        candidate = matches[0]
        if candidate == heard:
            return None
        ratio = difflib.SequenceMatcher(None, heard, candidate).ratio()
        return candidate if ratio >= 0.75 else None

    def listen_once(self, timeout: float = 30.0) -> str | None:
        """Captura + transcreve + corrige + fuzzy match. Retorna o comando final."""
        pcm = self._audio.record_utterance(timeout=timeout)
        if not pcm:
            return None
        raw = self.transcribe(pcm)
        if not raw:
            return None
        corrected = database.apply_speech_corrections(raw)
        matched = self.match_command(corrected)
        command = matched or corrected
        # Aprendizado automático pós-execução (só se houve correção real).
        if matched and matched.lower() != raw.strip().lower():
            similarity = difflib.SequenceMatcher(None, raw.strip().lower(), matched).ratio()
            if similarity >= 0.75:
                database.save_speech_correction(raw.strip().lower(), matched)
        return command

    def run_loop(
        self, handler: Callable[[str], str | None], *, speak_responses: bool = True
    ) -> None:
        """Loop contínuo: ouvir -> handler -> falar. Barge-in ativo."""
        self.start()
        try:
            while not self._stop.is_set():
                text = self.listen_once()
                if not text:
                    continue
                response = handler(text)
                if speak_responses and response:
                    self.speak(response)
        finally:
            self.stop()

    # ------------------------------------------------------------------
    # TTS com barge-in
    # ------------------------------------------------------------------

    def speak(self, text: str) -> None:
        if text and text.strip():
            self._tts_queue.put(text.strip())

    def _tts_worker(self) -> None:
        try:
            import pyttsx3

            engine = pyttsx3.init()
        except Exception as exc:
            logger.warning(f"voice: TTS indisponível ({exc})")
            return
        self._tts_engine = engine
        with contextlib.suppress(Exception):
            engine.setProperty("rate", 175)
        while not self._stop.is_set():
            try:
                text = self._tts_queue.get(timeout=0.5)
            except Exception:
                continue
            self._speaking.set()
            self._interrupt.clear()
            monitor = threading.Thread(
                target=self._barge_in_monitor, name="winbot-bargein", daemon=True
            )
            monitor.start()
            try:
                engine.say(text)
                engine.runAndWait()
            except Exception as exc:
                logger.debug(f"voice: tts interrompido/erro ({exc})")
            finally:
                self._speaking.clear()
                self._interrupt.set()
                monitor.join(timeout=0.5)
        with contextlib.suppress(Exception):
            engine.stop()

    def _barge_in_monitor(self) -> None:
        engine = self._tts_engine
        while self._speaking.is_set() and not self._interrupt.is_set():
            try:
                if self._audio.is_speaking():
                    if engine is not None:
                        with contextlib.suppress(Exception):
                            engine.stop()
                    self._interrupt.set()
                    break
            except Exception:
                pass
            time.sleep(0.1)
