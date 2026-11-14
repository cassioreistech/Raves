"""Captura de áudio resiliente (Etapa 3).

- Ring buffer de pré-roll (1,5s) para não cortar a primeira sílaba.
- AGC suave + filtro passa-alta 80 Hz.
- VAD neural (webrtcvad) em vez de RMS bruto.
- Auto-recovery de PortAudio (fone desconectado / troca de dispositivo).
- Silêncio adaptativo: frases curtas cortam em ~0,8s, longas aguardam ~1,5s.
"""

from __future__ import annotations

import collections
import queue
import threading
import time
from typing import Any

import numpy as np
import sounddevice as sd

from winbot.core.logger import logger

SAMPLE_RATE = 16000
BLOCK_SIZE = 1024  # ~64 ms a 16 kHz
PRE_ROLL_SECONDS = 1.5
VAD_FRAME = 480  # 30 ms a 16 kHz (exigido pelo webrtcvad)
VAD_AGGRESSIVENESS = 2


def _highpass_alpha(cutoff_hz: float, sample_rate: int) -> float:
    rc = 1.0 / (2.0 * 3.14159265 * cutoff_hz)
    dt = 1.0 / sample_rate
    return rc / (rc + dt)


class ResilientAudioCapture:
    """Captura de microfone com pre-roll, AGC, filtro e auto-recovery."""

    def __init__(
        self,
        sample_rate: int = SAMPLE_RATE,
        block_size: int = BLOCK_SIZE,
        pre_roll_seconds: float = PRE_ROLL_SECONDS,
    ) -> None:
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.pre_roll_len = max(1, int(sample_rate * pre_roll_seconds / block_size))
        self._pre_roll: collections.deque[np.ndarray] = collections.deque(maxlen=self.pre_roll_len)
        self._queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=64)
        self._stream: sd.InputStream | None = None
        self._running = False
        self._stop = threading.Event()
        self._noise_floor = 0.0
        self._calibrated = False
        self._alpha = _highpass_alpha(80.0, sample_rate)
        self._prev_x = 0.0
        self._prev_y = 0.0
        self._gain = 1.0
        self._vad = None
        self._last_block: np.ndarray | None = None
        self._lock = threading.Lock()

    def _lazy_vad(self) -> Any:
        if self._vad is None:
            import webrtcvad

            self._vad = webrtcvad.Vad(VAD_AGGRESSIVENESS)
        return self._vad

    def _audio_callback(self, indata: Any, frames: int, time_info: Any, status: Any) -> None:
        if status:
            logger.debug(f"audio: status={status}")
        try:
            block = indata[:, 0].copy() if getattr(indata, "ndim", 1) > 1 else indata.copy()
            arr = np.asarray(block, dtype=np.float32)
            self._last_block = arr
            self._queue.put_nowait(arr)
        except queue.Full:
            pass  # descarta bloco antigo em vez de travar a callback

    def _open_stream(self) -> None:
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            blocksize=self.block_size,
            callback=self._audio_callback,
        )
        self._stream.start()

    def start(self) -> None:
        if self._running:
            return
        self._open_stream()
        self._running = True
        self._stop.clear()

    def stop(self) -> None:
        self._running = False
        self._stop.set()
        stream = self._stream
        self._stream = None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception as exc:
                logger.debug(f"audio: erro ao fechar stream ({exc})")

    def _read_block(self, timeout: float = 1.0) -> np.ndarray | None:
        """Lê um bloco; em PortAudioError reabre o stream (auto-recovery)."""
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def _ensure_stream(self) -> None:
        if self._stream is None or not self._stream.active:
            try:
                self._open_stream()
                logger.info("audio: stream reinicializado")
            except Exception as exc:
                logger.warning(f"audio: falha ao reabrir stream: {exc}")

    def calibrate(self, duration: float = 0.5) -> float:
        """Mede o piso de ruído nos primeiros ``duration`` segundos de silêncio."""
        blocks = max(1, int(duration * self.sample_rate / self.block_size))
        samples: list[float] = []
        for _ in range(blocks):
            block = self._read_block(timeout=1.0)
            if block is None:
                continue
            samples.append(float(np.sqrt(np.mean(block**2))))
        if samples:
            self._noise_floor = float(np.median(samples))
            self._calibrated = True
        logger.info(f"audio: piso de ruido calibrado = {self._noise_floor:.4f}")
        return self._noise_floor

    def _process_block(self, block: np.ndarray) -> np.ndarray:
        """Filtro passa-alta 80 Hz + AGC suave."""
        # High-pass IIR (1a ordem).
        out = np.empty_like(block)
        x_prev = self._prev_x
        y_prev = self._prev_y
        for i in range(len(block)):
            x = float(block[i])
            y = self._alpha * (y_prev + x - x_prev)
            out[i] = y
            x_prev = x
            y_prev = y
        self._prev_x, self._prev_y = x_prev, y_prev

        # AGC: ganho suave em direcao ao RMS alvo.
        rms = float(np.sqrt(np.mean(out**2))) if out.size else 0.0
        target = 0.1
        if rms > 1e-5:
            desired = target / rms
            desired = float(min(4.0, max(0.5, desired)))
            self._gain = 0.9 * self._gain + 0.1 * desired
        out = out * self._gain
        return np.clip(out, -1.0, 1.0).astype(np.float32)

    def _is_speech(self, block: np.ndarray) -> bool:
        """VAD neural (webrtcvad) sobre frames de 30 ms."""
        vad = self._lazy_vad()
        pcm = (block * 32767.0).astype(np.int16).tobytes()
        # webrtcvad exige blocos de 10/20/30 ms (160/320/480 amostras a 16 kHz).
        frame_bytes = VAD_FRAME * 2  # 2 bytes por amostra int16
        speech_frames = 0
        total_frames = 0
        for offset in range(0, len(pcm) - frame_bytes + 1, frame_bytes):
            chunk = pcm[offset : offset + frame_bytes]
            if len(chunk) < frame_bytes:
                break
            total_frames += 1
            try:
                if vad.is_speech(chunk, self.sample_rate):
                    speech_frames += 1
            except Exception:
                return False
        if total_frames == 0:
            return False
        return speech_frames / total_frames >= 0.5

    def record_utterance(self, timeout: float = 30.0) -> bytes | None:
        """Captura uma fala completa (pre-roll + fala + silêncio final).

        Retorna PCM int16 (bytes) ou None se não houve fala / timeout.
        Silêncio adaptativo: fala curta (<1.5s) corta em 0.8s, longa em 1.5s.
        """
        if not self._running:
            self.start()
        self._ensure_stream()

        pre_roll: collections.deque[np.ndarray] = collections.deque(maxlen=self.pre_roll_len)
        speech_blocks: list[np.ndarray] = []
        in_speech = False
        speech_duration = 0.0
        silence_acc = 0.0
        started_at = time.monotonic()
        silence_threshold = 0.8

        while time.monotonic() - started_at < timeout:
            block = self._read_block(timeout=0.5)
            if block is None:
                self._ensure_stream()
                continue

            processed = self._process_block(block)
            is_speech = self._is_speech(processed)

            if not in_speech:
                pre_roll.append(processed)
                if is_speech:
                    in_speech = True
                    silence_acc = 0.0
                    # Anexa o pre-roll (passado imediato) para não cortar a 1a sílaba.
                    speech_blocks.extend(list(pre_roll))
                    speech_blocks.append(processed)
                    speech_duration = len(processed) / self.sample_rate
                continue

            # Em fala: acumula.
            speech_blocks.append(processed)
            speech_duration += len(processed) / self.sample_rate
            silence_threshold = 0.8 if speech_duration < 1.5 else 1.5

            if is_speech:
                silence_acc = 0.0
            else:
                silence_acc += len(processed) / self.sample_rate
                if silence_acc >= silence_threshold:
                    break

        if not speech_blocks or speech_duration < 0.3:
            return None

        audio = np.concatenate(speech_blocks)
        # Remove silêncio final excessivo (mantém 0.2s de cauda).
        tail = int(0.2 * self.sample_rate)
        if len(audio) > tail:
            audio = (
                audio[: len(audio) - int((silence_acc - 0.2) * self.sample_rate)]
                if silence_acc > 0.2
                else audio
            )
        pcm = (audio * 32767.0).clip(-32768, 32767).astype(np.int16)
        return pcm.tobytes()

    def is_speaking(self) -> bool:
        """True se a última captura detectou voz humana (barge-in).

        Usa o último bloco capturado pela callback (sem consumir a fila), para
        não atrapalhar uma gravação em andamento.
        """
        block = getattr(self, "_last_block", None)
        if block is None:
            return False
        try:
            return self._is_speech(self._process_block(block))
        except Exception:
            return False
