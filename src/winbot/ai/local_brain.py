"""Cérebro conversacional híbrido leve (Sprint B).

Comunica com o Ollama local (http://localhost:11434) usando apenas a stdlib
(urllib + json). Sem SDK pesado. keep_alive='2m' libera a RAM automaticamente.
Se o Ollama não estiver rodando, degrada graciosamente (is_available False).
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

from winbot.core import database
from winbot.core.learner import BehaviorLearner
from winbot.core.logger import logger

OLLAMA_URL = "http://localhost:11434/api/generate"
TAGS_URL = "http://localhost:11434/api/tags"
DEFAULT_MODEL = "qwen2.5:1.5b"
CACHE_TTL = 60.0
CLIPBOARD_LIMIT = 2000


class LocalBrain:
    def __init__(self, model: str | None = None, timeout: float = 0.3) -> None:
        self.model = model or self._configured_model()
        self.timeout = timeout
        self._available_cache: tuple[bool, float] = (False, 0.0)

    @staticmethod
    def _configured_model() -> str:
        try:
            from winbot.core.config import load_settings

            settings = load_settings()
            # licensing/settings não têm campo model; tenta um override opcional.
            extra = getattr(settings, "ai", None)
            if isinstance(extra, dict) and extra.get("model"):
                return str(extra["model"])
        except Exception:
            pass
        return DEFAULT_MODEL

    def is_available(self) -> bool:
        """Cache em memória de 60s para nunca atrasar o fluxo."""
        if os.environ.get("WINBOT_DISABLE_LOCAL_BRAIN"):
            return False
        available, checked_at = self._available_cache
        if time.monotonic() - checked_at < CACHE_TTL:
            return available
        result = False
        try:
            with urllib.request.urlopen(TAGS_URL, timeout=self.timeout) as response:
                result = response.status == 200
        except (urllib.error.URLError, TimeoutError, OSError):
            result = False
        self._available_cache = (result, time.monotonic())
        return result

    def _system_prompt(self, user_text: str) -> str:
        interests = database.get_interest_profile(limit=5)
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

        commands = (
            "abrir, fechar, focar, digitar, atalho, limpar temp, esperar, ps, repetir, "
            "historico, sugestoes, meu perfil, ler tela, clicar no texto, flow record"
        )
        prompt = (
            "Você é o assistente do WinBot (CLI de automação Windows). "
            "Responda em português, curto (máximo 2 frases), sem markdown. "
            "Comandos válidos: " + commands + ". "
            "Se o usuário pedir uma ação executável, responda APENAS com "
            "'ACTION: <comando_winbot>'. Caso contrário, responda conversacionalmente. "
            f"Interesses do usuário: {interest_text}. "
            f"Recomendações recentes: {rec_text}."
        )
        lowered = user_text.lower()
        if any(
            token in lowered
            for token in ("area de transferencia", "área de transferência", "clipboard")
        ):
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

    def ask(self, user_text: str) -> dict[str, Any]:
        """Retorna {'text': str, 'action': str | None}."""
        if not self.is_available():
            return {"text": "", "action": None}
        payload = {
            "model": self.model,
            "prompt": user_text,
            "system": self._system_prompt(user_text),
            "stream": False,
            "keep_alive": "2m",
            "options": {"temperature": 0.3, "num_predict": 120},
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
