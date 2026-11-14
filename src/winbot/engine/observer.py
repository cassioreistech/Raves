"""Observador de contexto 100% offline (Aprendizado Comportamental).

Lê apenas o processo e o título da janela em primeiro plano, classifica o
contexto e grava um evento leve no SQLite. Não usa rede, COM nem DLL externa.

PRIVACIDADE: títulos de janela podem conter dados sensíveis. Por isso são
truncados, **nunca** vão para loguru/audit (só para o DB local), o observador
pode ser desligado com ``WINBOT_OBSERVER_DISABLED=1`` e ``insights forget``
apaga tudo. Ele só roda quando ``shell``/``voice listen`` estão abertos.
"""

from __future__ import annotations

import os
import threading
from datetime import datetime
from typing import Any

from winbot.core import database
from winbot.core.logger import logger

# Janelas do próprio terminal/console: não são uso real do usuário.
_SELF_PROCESSES = frozenset(
    {
        "cmd.exe",
        "conhost.exe",
        "openconsole.exe",
        "powershell.exe",
        "pwsh.exe",
        "py.exe",
        "python.exe",
        "winbot.exe",
        "windowsterminal.exe",
        "wt.exe",
    }
)
_IGNORED_TITLES = frozenset({"", "program manager", "windows input experience"})

# Ordem importa: "lo-fi beats - youtube" cai em musica antes de midia.
_CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "musica",
        (
            "spotify",
            "youtube music",
            "deezer",
            "soundcloud",
            "tidal",
            "lofi",
            "lo-fi",
            "rock",
            "sertanejo",
            "jazz",
            "mpb",
            "playlist",
            "album",
            "música",
            "musica",
            "song",
            "audio",
        ),
    ),
    (
        "desenvolvimento",
        (
            "visual studio code",
            "vs code",
            "vscode",
            "pycharm",
            "intellij",
            "github",
            "git ",
            "localhost",
            "debug",
            "pytest",
            "opencode",
            "cursor",
            "terminal",
            "powershell",
        ),
    ),
    (
        "pesquisa",
        (
            "google",
            "chrome",
            "edge",
            "firefox",
            "stackoverflow",
            "wikipedia",
            "pesquisa",
            "search",
            "docs",
        ),
    ),
    (
        "midia",
        ("youtube", "netflix", "vlc", "twitch", "player", "filme", "video", "vídeo"),
    ),
    (
        "produtividade",
        ("excel", "word", "outlook", "teams", "notion", "planilha", "email", "e-mail"),
    ),
    (
        "estudos",
        ("curso", "aula", "estudo", "udemy", "coursera", "kindle", "pdf", "livro"),
    ),
    (
        "financas",
        ("banco", "finanças", "financas", "investimento", "bitcoin", "ações", "acoes"),
    ),
    ("jogos", ("steam", "epic games", "xbox", "jogo", "game")),
)


def classify(app_name: str, title: str) -> tuple[str, list[str]]:
    """Retorna ``(categoria, keywords)``. Categoria 'outros' quando nada bate."""
    haystack = f"{title} {app_name}".lower()
    category = "outros"
    matched: list[str] = []
    for name, keywords in _CATEGORY_RULES:
        hits = [keyword for keyword in keywords if keyword in haystack]
        if hits:
            category = name
            matched = hits
            break

    stem = app_name.lower().removesuffix(".exe").strip()
    keywords = list(dict.fromkeys([*matched, stem]))[:4] if stem else matched[:4]
    return category, [item for item in keywords if item]


class ContextObserver:
    """Captura a janela ativa em uma thread daemon, com parada limpa via Event."""

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._interval = 30
        self._last_signature: tuple[str, str] | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def read_foreground(self) -> tuple[str, str] | None:
        """``(process_name, window_title)`` ou None para janelas ignoradas."""
        try:
            import psutil
            import win32gui
            import win32process
        except ImportError:  # pragma: no cover - projeto é Windows-only
            return None
        try:
            hwnd = win32gui.GetForegroundWindow()
            if not hwnd:
                return None
            title = (win32gui.GetWindowText(hwnd) or "").strip()
            if len(title) < 2 or title.lower() in _IGNORED_TITLES:
                return None
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if not pid:
                return None
            process_name = psutil.Process(pid).name()
        except Exception as exc:  # janela fechou / acesso negado: nunca derruba a thread
            logger.debug(f"observer: janela ignorada ({exc})")
            return None
        if process_name.lower() in _SELF_PROCESSES:
            return None
        return process_name, title

    def capture_once(self) -> dict[str, Any] | None:
        """Classifica e persiste um evento. None = ignorado ou duplicado."""
        foreground = self.read_foreground()
        if foreground is None:
            return None
        app_name, title = foreground
        signature = (app_name.lower(), title)
        if signature == self._last_signature:
            return None
        self._last_signature = signature

        category, keywords = classify(app_name, title)
        now = datetime.now().astimezone()
        dow = now.weekday()
        bucket = database.hour_bucket_for(now.hour)
        saved = database.log_activity_event(
            app_name, title, category, dow, bucket, captured_at=now.isoformat(timespec="seconds")
        )
        if not saved:
            return None
        for keyword in keywords:
            database.upsert_interest(category, keyword)
        return {
            "app_name": app_name,
            "window_title": title,
            "category": category,
            "keywords": keywords,
            "day_of_week": dow,
            "hour_bucket": bucket,
        }

    def start_background_watch(self, interval_seconds: int = 30) -> None:
        """Inicia a thread daemon. ``WINBOT_OBSERVER_DISABLED=1`` desliga."""
        self._interval = max(5, int(interval_seconds))
        if self.running:
            return
        if os.environ.get("WINBOT_OBSERVER_DISABLED"):
            logger.debug("ContextObserver desligado por WINBOT_OBSERVER_DISABLED")
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="winbot-context-observer", daemon=True
        )
        self._thread.start()

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                try:
                    self.capture_once()
                except Exception as exc:  # telemetria nunca pode derrubar a CLI
                    logger.debug(f"observer: captura ignorada ({exc})")
                if self._stop.wait(self._interval):
                    break
        finally:
            logger.debug("ContextObserver encerrado")

    def stop(self) -> None:
        """Sinaliza parada e aguarda no máximo 2s (não bloqueia o shell)."""
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        self._thread = None
