"""Cérebro conversacional híbrido (Sprint B) — ciclo de vida gerenciado.

Comunica com o Ollama local (http://localhost:11434) usando apenas a stdlib
(urllib + json). Sem SDK pesado. keep_alive='90s' libera a RAM automaticamente.
Se o Ollama não estiver instalado, degrada graciosamente.
"""

from __future__ import annotations

import atexit
import contextlib
import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from raves.core.config import load_settings
from raves.core.learner import BehaviorLearner
from raves.core.logger import logger

OLLAMA_URL = "http://localhost:11434/api/generate"
TAGS_URL = "http://localhost:11434/api/tags"
DEFAULT_MODEL = "qwen2.5:1.5b"
CACHE_TTL = 60.0
CLIPBOARD_LIMIT = 2000
SERVER_STARTUP_TIMEOUT = 3.0

# Processo gerenciado pelo RAVES (encerrado ao sair).
_managed_process: subprocess.Popen | None = None
_managed_lock = __import__("threading").Lock()


def _ollama_executable() -> str | None:
    found = shutil.which("ollama")
    if found:
        return found
    candidate = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
    if candidate.is_file():
        return str(candidate)
    return None


def _configured_model() -> str:
    try:
        load_settings()
    except Exception:
        return DEFAULT_MODEL
    # Permite override em ~/.raves/settings.yaml via chave ai.model
    try:
        import yaml

        path = None
        try:
            from raves.core.config import user_config_path

            path = user_config_path()
        except Exception:
            path = None
        if path is not None and path.exists():
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if isinstance(data, dict):
                ai = data.get("ai")
                if isinstance(ai, dict) and ai.get("model"):
                    return str(ai["model"])
                if data.get("ollama_model"):
                    return str(data["ollama_model"])
    except Exception:
        pass
    return DEFAULT_MODEL


class LocalBrain:
    def __init__(self, model: str | None = None, timeout: float = 0.3) -> None:
        self.model = model or _configured_model()
        self.timeout = timeout
        self._available_cache: tuple[bool, float] = (False, 0.0)

    # ------------------------------------------------------------------
    # Ciclo de vida do servidor
    # ------------------------------------------------------------------

    def ensure_server_running(self) -> bool:
        """Inicia ollama serve se a porta estiver fechada. Retorna True se ativo."""
        if self._ping():
            return True
        exe = _ollama_executable()
        if exe is None:
            logger.debug("local_brain: ollama.exe não encontrado")
            return False
        env = os.environ.copy()
        env["OLLAMA_MAX_LOADED_MODELS"] = "1"
        env["OLLAMA_NUM_PARALLEL"] = "1"
        try:
            proc = subprocess.Popen(
                [exe, "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
                env=env,
            )
        except OSError as exc:
            logger.debug(f"local_brain: falha ao iniciar ollama: {exc}")
            return False
        global _managed_process
        with _managed_lock:
            _managed_process = proc
        # Aguarda até 3s pela porta.
        deadline = time.monotonic() + SERVER_STARTUP_TIMEOUT
        while time.monotonic() < deadline:
            if self._ping():
                return True
            time.sleep(0.3)
        return self._ping()

    def _ping(self) -> bool:
        try:
            with urllib.request.urlopen(TAGS_URL, timeout=self.timeout) as response:
                return response.status == 200
        except (urllib.error.URLError, TimeoutError, OSError):
            return False

    def is_available(self) -> bool:
        """Cache em memória de 60s. Tenta iniciar o servidor se necessário."""
        if os.environ.get("RAVES_DISABLE_LOCAL_BRAIN"):
            return False
        available, checked_at = self._available_cache
        if time.monotonic() - checked_at < CACHE_TTL:
            return available
        result = self._ping()
        if not result and self.ensure_server_running():
            # Tenta acordar o servidor uma vez.
            result = self._ping()
        self._available_cache = (result, time.monotonic())
        return result

    def shutdown_if_managed(self) -> None:
        """Encerra o ollama serve apenas se foi o RAVES que o iniciou."""
        global _managed_process
        with _managed_lock:
            proc = _managed_process
            _managed_process = None
        if proc is None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=5.0)
        except Exception as exc:
            logger.debug(f"local_brain: encerramento do ollama falhou ({exc})")
            with contextlib.suppress(Exception):
                proc.kill()

    # ------------------------------------------------------------------
    # Consulta
    # ------------------------------------------------------------------

    def ask(self, user_text: str) -> dict[str, Any]:
        """Retorna {'text': str, 'action': str | None}."""
        if not self.is_available():
            return {"text": "", "action": None}
        payload = {
            "model": self.model,
            "prompt": user_text,
            "system": self._system_prompt(user_text),
            "stream": False,
            "keep_alive": "90s",
            "options": {"num_ctx": 1024, "num_predict": 140, "temperature": 0.3},
        }
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            OLLAMA_URL,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30.0) as response:
                raw = response.read().decode("utf-8", errors="replace")
            parsed = json.loads(raw)
            text = str(parsed.get("response", "")).strip()
        except (
            urllib.error.URLError,
            TimeoutError,
            OSError,
            json.JSONDecodeError,
            ValueError,
        ) as exc:
            logger.debug(f"local_brain: falha na chamada ({exc})")
            self._available_cache = (False, time.monotonic())
            return {"text": "", "action": None}

        action: str | None = None
        if text.upper().startswith("ACTION:"):
            action = text[len("ACTION:") :].strip()
            text = ""
        return {"text": text, "action": action}

    def _system_prompt(self, user_text: str) -> str:
        from raves.core import database as _db

        interests = _db.get_interest_profile(limit=5)
        interest_text = (
            ", ".join(
                f"{item['keyword']} ({item['category']}, peso {item['effective_weight']:.2f})"
                for item in interests
            )
            or "nenhum interesse aprendido ainda"
        )
        try:
            learner = BehaviorLearner()
            learner.analyze_patterns()
            recommendations = learner.get_recommendations()
        except Exception:
            recommendations = []
        rec_text = " | ".join(recommendations[:3]) or "nenhuma"

        # Memoria conversacional (Etapa 10): ultimos 4 turnos para dialogo continuo.
        turns_text = ""
        try:
            recent = _db.get_recent_turns(limit=4)
            if recent:
                turns_text = " | ".join(f"{item['role']}: {item['text'][:80]}" for item in recent)
        except Exception:
            turns_text = ""

        commands = (
            "abrir, fechar, focar, digitar, atalho, limpar temp, esperar, ps, repetir, "
            "historico, sugestoes, meu perfil, ler tela, clicar no texto, flow record"
        )
        prompt = (
            "Você é o assistente do RAVES (CLI de automação Windows). "
            "Responda em português, curto (máximo 2 frases), sem markdown. "
            "Comandos válidos: " + commands + ". "
            "Se o usuário pedir uma ação executável, responda APENAS com "
            "'ACTION: <comando_raves>'. Caso contrário, responda conversacionalmente. "
            f"Interesses do usuário: {interest_text}. "
            f"Recomendações recentes: {rec_text}."
            + (f" Histórico recente: {turns_text}." if turns_text else "")
        )
        lowered = user_text.lower()
        tokens = ("area de transferencia", "área de transferência", "clipboard")
        if any(token in lowered for token in tokens):
            try:
                import pyperclip

                clip = pyperclip.paste() or ""
            except Exception:
                clip = ""
            if clip.strip():
                prompt += (
                    " Conteúdo da área de transferência (truncado): "
                    + clip.strip()[:CLIPBOARD_LIMIT]
                )
        return prompt


def shutdown_if_managed() -> None:
    """Encerra o ollama serve apenas se foi o RAVES que o iniciou (módulo-level)."""
    global _managed_process
    with _managed_lock:
        proc = _managed_process
        _managed_process = None
    if proc is None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=5.0)
    except Exception as exc:
        logger.debug(f"local_brain: encerramento do ollama falhou ({exc})")
        with contextlib.suppress(Exception):
            proc.kill()


# Encerramento limpo ao sair do processo Python (cobre CLI e tray).
atexit.register(shutdown_if_managed)
