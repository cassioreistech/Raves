"""Gatilhos reativos event-driven (Sprint B, ~0% CPU).

Em vez de polling, usa ``watchdog`` (ReadDirectoryChangesW no Windows) para
arquivos e uma única thread de baixa frequência para janelas. O robô dorme e
só acorda no milissegundo em que o evento ocorre.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from winbot.core.logger import audit, logger

TRIGGERS_FILE = Path.home() / ".winbot" / "triggers.yaml"
DEBOUNCE_DEFAULT = 1.5


class TriggerRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    event: str  # "file_created" | "window_opened"
    path: str | None = None
    extensions: list[str] = Field(default_factory=list)
    window_title: str | None = None
    run: str
    enabled: bool = True
    debounce_seconds: float = DEBOUNCE_DEFAULT


def _normalize_ext(ext: str) -> str:
    value = ext.strip().lower()
    if not value:
        return ""
    return value if value.startswith(".") else f".{value}"


class _FileHandler(FileSystemEventHandler):
    """Handler watchdog com debounce por arquivo."""

    def __init__(self, manager: TriggerManager, rule: TriggerRule) -> None:
        self.manager = manager
        self.rule = rule
        self._timers: dict[str, threading.Timer] = {}
        self._lock = threading.Lock()

    def on_created(self, event: Any) -> None:
        if event.is_directory:
            return
        path = Path(event.src_path)
        exts = {_normalize_ext(e) for e in self.rule.extensions}
        if exts and path.suffix.lower() not in exts:
            return
        self._debounce(path)

    def _debounce(self, path: Path) -> None:
        key = str(path)
        with self._lock:
            existing = self._timers.pop(key, None)
            if existing is not None:
                existing.cancel()
            timer = threading.Timer(self.rule.debounce_seconds, self._fire, args=(path,))
            timer.daemon = True
            timer.start()
            self._timers[key] = timer

    def _fire(self, path: Path) -> None:
        with self._lock:
            self._timers.pop(str(path), None)
        logger.info(f"trigger '{self.rule.name}': arquivo criado {path}")
        audit(f"trigger file_created name={self.rule.name} path={path}")
        self.manager.execute(self.rule, context=str(path))


class TriggerManager:
    def __init__(self, rules: list[TriggerRule] | None = None) -> None:
        self.rules: list[TriggerRule] = list(rules) if rules is not None else self._load()
        self._observer: Any = None
        self._window_thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._last_windows: dict[str, str] = {}
        self._executor: Callable[[TriggerRule, str], None] | None = None

    # ------------------------------------------------------------------
    # Persistência
    # ------------------------------------------------------------------

    @staticmethod
    def _load() -> list[TriggerRule]:
        if not TRIGGERS_FILE.exists():
            return []
        try:
            raw = yaml.safe_load(TRIGGERS_FILE.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            logger.warning(f"triggers: YAML inválido ({exc})")
            return []
        items = raw.get("triggers", []) if isinstance(raw, dict) else []
        rules: list[TriggerRule] = []
        for item in items:
            try:
                rules.append(TriggerRule.model_validate(item))
            except ValidationError as exc:
                logger.warning(f"triggers: regra inválida ignorada: {exc}")
        return rules

    @staticmethod
    def _save(rules: list[TriggerRule]) -> None:
        TRIGGERS_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = {"triggers": [rule.model_dump() for rule in rules]}
        TRIGGERS_FILE.write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )

    def reload(self) -> None:
        self.rules = self._load()

    def add(self, rule: TriggerRule) -> None:
        # substitui regra com mesmo nome
        self.rules = [existing for existing in self.rules if existing.name != rule.name]
        self.rules.append(rule)
        self._save(self.rules)

    def remove(self, name: str) -> bool:
        before = len(self.rules)
        self.rules = [rule for rule in self.rules if rule.name != name]
        if len(self.rules) != before:
            self._save(self.rules)
            return True
        return False

    def list_rules(self) -> list[dict[str, Any]]:
        return [rule.model_dump() for rule in self.rules]

    # ------------------------------------------------------------------
    # Execução de uma regra
    # ------------------------------------------------------------------

    def set_executor(self, executor: Callable[[TriggerRule, str], None]) -> None:
        self._executor = executor

    def execute(self, rule: TriggerRule, context: str = "") -> None:
        if not rule.enabled:
            return
        if self._executor is not None:
            try:
                self._executor(rule, context)
                return
            except Exception as exc:
                logger.warning(f"trigger '{rule.name}': executor falhou ({exc})")
        # fallback padrão: tenta rodar como comando do dispatcher
        try:
            from winbot.core.dispatcher import execute_natural_command

            execute_natural_command(rule.run, apply=True)
        except Exception as exc:
            logger.warning(f"trigger '{rule.name}': fallback falhou ({exc})")

    # ------------------------------------------------------------------
    # Daemon
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._observer is not None or self._window_thread is not None:
            return
        self._stop.clear()

        # file_created: um Observer por diretório único.
        directories = {
            rule.path
            for rule in self.rules
            if rule.enabled and rule.event == "file_created" and rule.path
        }
        if directories:
            observer = Observer()
            self._observer = observer
            for directory in directories:
                path = Path(directory).expanduser()
                if not path.is_dir():
                    logger.warning(f"trigger: diretório inexistente {path}")
                    continue
                handlers = [
                    _FileHandler(self, rule)
                    for rule in self.rules
                    if rule.enabled
                    and rule.event == "file_created"
                    and rule.path
                    and Path(rule.path).expanduser() == path
                ]
                for handler in handlers:
                    observer.schedule(handler, str(path), recursive=False)
            try:
                observer.start()
            except Exception as exc:
                logger.warning(f"trigger: observer não iniciou ({exc})")
                self._observer = None

        # window_opened: uma única thread de polling de baixa frequência.
        if any(rule.enabled and rule.event == "window_opened" for rule in self.rules):
            self._window_thread = threading.Thread(
                target=self._window_loop, name="winbot-trigger-windows", daemon=True
            )
            self._window_thread.start()

        logger.info(f"trigger watch: {len(self.rules)} regra(s) ativa(s)")

    def stop(self) -> None:
        self._stop.set()
        if self._observer is not None:
            try:
                self._observer.stop()
                self._observer.join(timeout=2.0)
            except Exception:
                pass
            self._observer = None
        if self._window_thread is not None:
            self._window_thread.join(timeout=2.0)
            self._window_thread = None

    def _window_loop(self) -> None:
        try:
            import win32gui
        except ImportError:
            return
        while not self._stop.is_set():
            try:
                hwnd = win32gui.GetForegroundWindow()
                title = (win32gui.GetWindowText(hwnd) or "").strip() if hwnd else ""
            except Exception:
                title = ""
            if title:
                for rule in self.rules:
                    if not rule.enabled or rule.event != "window_opened":
                        continue
                    needle = (rule.window_title or "").lower()
                    if not needle or needle not in title.lower():
                        continue
                    # dispara só na transição (evita spam a cada 2s)
                    if self._last_windows.get(rule.name) == title:
                        continue
                    self._last_windows[rule.name] = title
                    logger.info(f"trigger '{rule.name}': janela aberta '{title}'")
                    audit(f"trigger window_opened name={rule.name} title={title!r}")
                    self.execute(rule, context=title)
            self._stop.wait(2.0)
