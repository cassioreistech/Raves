import contextlib
from unittest.mock import MagicMock

import numpy as np

from winbot.engine.audio_pipeline import ResilientAudioCapture


def test_process_block_preserva_tamanho_e_filtra() -> None:
    cap = ResilientAudioCapture(sample_rate=16000, block_size=64)
    block = np.ones(64, dtype=np.float32) * 0.5
    out = cap._process_block(block)
    assert out.shape == block.shape
    assert out.dtype == np.float32
    # O filtro passa-alta altera o sinal (nao e copia).
    assert not np.array_equal(out, block)


def test_record_utterance_inclui_pre_roll(monkeypatch) -> None:
    cap = ResilientAudioCapture(sample_rate=100, block_size=4, pre_roll_seconds=0.5)
    cap._running = True
    cap._stream = MagicMock(active=True)
    monkeypatch.setattr(cap, "_open_stream", lambda: None)
    # 6 blocos de silencio (pre-roll) + 3 de fala + 3 de silencio (corte)
    silence = [np.zeros(4, dtype=np.float32) for _ in range(6)]
    # Sinal variavel (senoide) para nao ser eliminado pelo filtro passa-alta.
    t = np.arange(4, dtype=np.float32)
    speech = [np.sin(2 * np.pi * 0.25 * t + i).astype(np.float32) * 0.5 for i in range(3)]
    tail = [np.zeros(4, dtype=np.float32) for _ in range(25)]
    seq = iter(silence + speech + tail)
    monkeypatch.setattr(cap, "_read_block", lambda timeout=1.0: next(seq, None))
    monkeypatch.setattr(cap, "_is_speech", lambda b: float(np.mean(np.abs(b))) > 0.01)

    pcm = cap.record_utterance(timeout=10.0)
    assert pcm is not None
    # pre-roll (6) + fala (3) = pelo menos 9 blocos * 4 amostras * 2 bytes
    assert len(pcm) >= 9 * 4 * 2


def test_record_utterance_retorna_none_sem_fala(monkeypatch) -> None:
    cap = ResilientAudioCapture(sample_rate=100, block_size=4, pre_roll_seconds=0.2)
    cap._running = True
    cap._stream = MagicMock(active=True)
    monkeypatch.setattr(cap, "_open_stream", lambda: None)
    seq = iter([np.zeros(4, dtype=np.float32) for _ in range(20)])
    monkeypatch.setattr(cap, "_read_block", lambda timeout=1.0: next(seq, None))
    monkeypatch.setattr(cap, "_is_speech", lambda b: False)
    assert cap.record_utterance(timeout=2.0) is None


def test_auto_recovery_reabre_stream_quando_ausente(monkeypatch) -> None:
    cap = ResilientAudioCapture()
    cap._running = True
    fake_stream = MagicMock()
    fake_stream.active = True
    monkeypatch.setattr(cap, "_open_stream", lambda: setattr(cap, "_stream", fake_stream))
    cap._stream = None
    cap._ensure_stream()
    assert cap._stream is fake_stream


def test_is_speaking_usa_ultimo_bloco_sem_consumir_fila(mocker) -> None:
    cap = ResilientAudioCapture()
    block = np.ones(64, dtype=np.float32) * 0.5
    cap._last_block = block
    mocker.patch.object(cap, "_is_speech", return_value=True)
    assert cap.is_speaking() is True
    mocker.patch.object(cap, "_is_speech", return_value=False)
    assert cap.is_speaking() is False


def test_calibrate_medir_piso_de_ruido(monkeypatch) -> None:
    cap = ResilientAudioCapture(sample_rate=100, block_size=4)
    cap._running = True
    seq = iter([np.full(4, 0.05, dtype=np.float32) for _ in range(5)])
    monkeypatch.setattr(cap, "_read_block", lambda timeout=1.0: next(seq, None))
    floor = cap.calibrate(duration=0.2)
    assert floor > 0
    assert cap._calibrated is True


def test_callback_nao_trava_em_fila_cheia() -> None:
    cap = ResilientAudioCapture(sample_rate=100, block_size=4)
    # Enche a fila (ignora Full: e exatamente o que queremos testar)
    for _ in range(cap._queue.maxsize + 5):
        with contextlib.suppress(Exception):
            cap._queue.put_nowait(np.zeros(4, dtype=np.float32))
    # Callback deve descartar sem levantar.
    indata = np.ones((4, 1), dtype=np.float32)
    cap._audio_callback(indata, 4, None, None)
    assert cap._last_block is not None
