"""Persistência local em SQLite (Etapa 1 de Blindagem).

Banco em ``~/.winbot/winbot.db``. Cada função abre sua própria conexão curta,
aplica ``journal_mode=WAL`` e ``synchronous=NORMAL`` e fecha — seguro para a CLI,
para o loop ``shell`` e para chamadas concorrentes. Nenhum segredo é gravado em
log; ``command_history.raw_command`` fica em texto claro no disco local porque
``repetir`` precisa reexecutá-lo (veja ``dispatcher.redact_command`` para exibição).
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_DB_PATH = Path.home() / ".winbot" / "winbot.db"

# Comandos de memória: nunca podem ser alvo de `repetir` (evita loop infinito).
REPEAT_PREFIXES: tuple[str, ...] = ("repetir", "faz de novo")
HISTORY_PREFIXES: tuple[str, ...] = (
    "historico",
    "histórico",
    "ultimos comandos",
    "últimos comandos",
)
MEMORY_PREFIXES: tuple[str, ...] = REPEAT_PREFIXES + HISTORY_PREFIXES

_SCHEMA = """
CREATE TABLE IF NOT EXISTS installed_apps (
    name        TEXT PRIMARY KEY,
    target_path TEXT NOT NULL,
    source      TEXT,
    updated_at  TEXT
);
CREATE TABLE IF NOT EXISTS command_history (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_command    TEXT NOT NULL,
    success        INTEGER NOT NULL,
    result_message TEXT,
    executed_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_history_success_id
    ON command_history(success, id DESC);
"""


def db_path() -> Path:
    """Caminho efetivo. ``WINBOT_DB_PATH`` permite isolar o banco em testes."""
    override = os.environ.get("WINBOT_DB_PATH")
    return Path(override) if override else DEFAULT_DB_PATH


def _utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5.0)
    try:
        # Em TODA conexão, conforme a especificação da Etapa 1.
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.row_factory = sqlite3.Row
        conn.executescript(_SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """Materializa o arquivo e as duas tabelas (idempotente)."""
    with _connect():
        pass


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def is_memory_command(raw: str) -> bool:
    lowered = raw.strip().lower()
    return any(lowered.startswith(prefix) for prefix in MEMORY_PREFIXES)


# ---------------------------------------------------------------------------
# installed_apps
# ---------------------------------------------------------------------------


def upsert_apps(apps: list[tuple[str, str, str]]) -> int:
    """Grava ``(name, target_path, source)``; conflito de nome atualiza o alvo."""
    now = _utcnow()
    rows = [
        (name.strip().lower(), target_path.strip(), source, now)
        for name, target_path, source in apps
        if name and name.strip() and target_path and target_path.strip()
    ]
    if not rows:
        return 0
    with _connect() as conn:
        conn.executemany(
            """
            INSERT INTO installed_apps (name, target_path, source, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                target_path = excluded.target_path,
                source      = excluded.source,
                updated_at  = excluded.updated_at
            """,
            rows,
        )
    return len(rows)


def find_app(query: str) -> str | None:
    """Resolve um nome para ``target_path``: exato, depois LIKE pelo nome mais curto."""
    key = query.strip().lower()
    if not key:
        return None
    with _connect() as conn:
        exact = conn.execute(
            "SELECT target_path FROM installed_apps WHERE name = ?", (key,)
        ).fetchone()
        if exact is not None:
            return str(exact["target_path"])
        partial = conn.execute(
            "SELECT target_path FROM installed_apps "
            "WHERE name LIKE ? ESCAPE '\\' "
            "ORDER BY LENGTH(name) ASC, name ASC LIMIT 1",
            (f"%{_escape_like(key)}%",),
        ).fetchone()
        return str(partial["target_path"]) if partial is not None else None


def count_apps() -> int:
    with _connect() as conn:
        return int(conn.execute("SELECT COUNT(*) FROM installed_apps").fetchone()[0])


def get_apps(filter_text: str | None = None) -> list[dict[str, Any]]:
    """Lista apps ordenados por nome; ``--filter`` usa LIKE case-insensitive."""
    with _connect() as conn:
        if filter_text and filter_text.strip():
            rows = conn.execute(
                "SELECT name, target_path, source, updated_at FROM installed_apps "
                "WHERE name LIKE ? ESCAPE '\\' ORDER BY name ASC",
                (f"%{_escape_like(filter_text.strip().lower())}%",),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT name, target_path, source, updated_at FROM installed_apps ORDER BY name ASC"
            ).fetchall()
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# command_history
# ---------------------------------------------------------------------------


def log_command(raw_command: str, success: bool, result_message: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO command_history "
            "(raw_command, success, result_message, executed_at) VALUES (?, ?, ?, ?)",
            (raw_command, 1 if success else 0, result_message, _utcnow()),
        )


def get_last_successful_command() -> str | None:
    """Último comando bem-sucedido que NÃO seja de memória (anti-loop)."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT raw_command FROM command_history WHERE success = 1 ORDER BY id DESC LIMIT 50"
        ).fetchall()
    for row in rows:
        raw = str(row["raw_command"]).strip()
        if raw and not is_memory_command(raw):
            return raw
    return None


def get_recent_history(limit: int = 10) -> list[dict[str, Any]]:
    """Últimos comandos (mais recente primeiro). ``success`` é ``bool``."""
    capped = max(1, min(int(limit), 200))
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, raw_command, success, result_message, executed_at "
            "FROM command_history ORDER BY id DESC LIMIT ?",
            (capped,),
        ).fetchall()
    return [
        {
            "id": int(row["id"]),
            "raw_command": str(row["raw_command"]),
            "success": bool(row["success"]),
            "result_message": str(row["result_message"] or ""),
            "executed_at": str(row["executed_at"]),
        }
        for row in rows
    ]
