"""Persistência local em SQLite (Etapa 1 de Blindagem).

Banco em ``~/.winbot/winbot.db``. Cada função abre sua própria conexão curta,
aplica ``journal_mode=WAL`` e ``synchronous=NORMAL`` e fecha — seguro para a CLI,
para o loop ``shell`` e para chamadas concorrentes. Nenhum segredo é gravado em
log; ``command_history.raw_command`` fica em texto claro no disco local porque
``repetir`` precisa reexecutá-lo (veja ``dispatcher.redact_command`` para exibição).
"""

from __future__ import annotations

import json
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
INSIGHT_PREFIXES: tuple[str, ...] = (
    "o que voce aprendeu",
    "o que você aprendeu",
    "me de uma dica",
    "me dê uma dica",
    "sugestoes",
    "sugestões",
    "meu perfil",
)
MEMORY_PREFIXES: tuple[str, ...] = REPEAT_PREFIXES + HISTORY_PREFIXES + INSIGHT_PREFIXES

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

-- Aprendizado comportamental (100% offline).
CREATE TABLE IF NOT EXISTS activity_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    app_name     TEXT,
    window_title TEXT,
    category     TEXT,
    day_of_week  INTEGER,
    hour_bucket  TEXT,
    captured_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_activity_context
    ON activity_events(day_of_week, hour_bucket);
CREATE TABLE IF NOT EXISTS user_interests (
    category  TEXT,
    keyword   TEXT,
    weight    REAL DEFAULT 1.0,
    last_seen TEXT,
    PRIMARY KEY (category, keyword)
);
CREATE TABLE IF NOT EXISTS learned_routines (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    trigger_context   TEXT UNIQUE,
    suggested_actions TEXT,
    confidence        REAL,
    times_observed    INTEGER,
    last_suggested    TEXT
);
-- Tabela auxiliar minima para cooldown de sugestoes e metadados do app.
CREATE TABLE IF NOT EXISTS app_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

_HOUR_BUCKETS = ("madrugada", "manha", "tarde", "noite")
_INTEREST_HALF_LIFE_DAYS = 45.0


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
    """Materializa o arquivo e todas as tabelas (idempotente)."""
    with _connect():
        pass


def hour_bucket_for(hour: int) -> str:
    """06-11 manha · 12-17 tarde · 18-22 noite · 23-05 madrugada."""
    if 6 <= hour <= 11:
        return "manha"
    if 12 <= hour <= 17:
        return "tarde"
    if 18 <= hour <= 22:
        return "noite"
    return "madrugada"


def parse_local_context(iso_timestamp: str) -> tuple[int, str]:
    """Converte um ISO timestamp para ``(day_of_week, hour_bucket)`` no fuso local.

    ``day_of_week`` segue ``datetime.weekday()``: 0 = segunda ... 6 = domingo.
    """
    moment = datetime.fromisoformat(iso_timestamp)
    # astimezone() sem argumento converte para o fuso LOCAL (naive -> assume local).
    moment = moment.astimezone()
    return moment.weekday(), hour_bucket_for(moment.hour)


def is_insight_command(raw: str) -> bool:
    lowered = raw.strip().lower()
    return any(lowered.startswith(prefix) for prefix in INSIGHT_PREFIXES)


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


# ---------------------------------------------------------------------------
# Telemetria passiva (activity_events)
# ---------------------------------------------------------------------------

MAX_TITLE_LENGTH = 200


def log_activity_event(
    app_name: str,
    window_title: str,
    category: str,
    day_of_week: int,
    hour_bucket: str,
    captured_at: str | None = None,
) -> bool:
    """Grava um evento leve. Retorna False se for igual ao último (sem duplicar).

    Titulos sao truncados e **nunca** vao para loguru/audit: so para o SQLite
    local. O observador pode ser desligado com WINBOT_OBSERVER_DISABLED=1.
    """
    title = window_title.strip()[:MAX_TITLE_LENGTH]
    now = captured_at or _utcnow()
    with _connect() as conn:
        last = conn.execute(
            "SELECT app_name, window_title FROM activity_events ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if last is not None and (
            str(last["app_name"]) == app_name and str(last["window_title"]) == title
        ):
            return False
        conn.execute(
            "INSERT INTO activity_events "
            "(app_name, window_title, category, day_of_week, hour_bucket, captured_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (app_name, title, category, int(day_of_week), hour_bucket, now),
        )
    return True


def count_activity_events() -> int:
    with _connect() as conn:
        return int(conn.execute("SELECT COUNT(*) FROM activity_events").fetchone()[0])


def get_active_hours(limit: int = 4) -> list[dict[str, Any]]:
    """Faixas de horario mais ativas (para 'insights profile')."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT hour_bucket, COUNT(*) AS total FROM activity_events "
            "GROUP BY hour_bucket ORDER BY total DESC LIMIT ?",
            (max(1, min(int(limit), 10)),),
        ).fetchall()
    return [{"hour_bucket": str(row["hour_bucket"]), "total": int(row["total"])} for row in rows]


def get_activity_context_counts() -> list[dict[str, Any]]:
    """Agrega (dia, faixa, categoria, app) com total e dias distintos."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT day_of_week, hour_bucket, category, app_name, "
            "COUNT(*) AS total, COUNT(DISTINCT substr(captured_at, 1, 10)) AS distinct_days "
            "FROM activity_events "
            "GROUP BY day_of_week, hour_bucket, category, app_name"
        ).fetchall()
    return [dict(row) for row in rows]


def get_command_context_counts() -> list[dict[str, Any]]:
    """Agrega comandos bem-sucedidos por (dia, faixa, comando), em hora LOCAL.

    Feito em Python porque ``executed_at`` e UTC e o contexto e local.
    """
    with _connect() as conn:
        rows = conn.execute(
            "SELECT raw_command, executed_at FROM command_history WHERE success = 1"
        ).fetchall()

    grouped: dict[tuple[int, str, str], dict[str, Any]] = {}
    for row in rows:
        raw = str(row["raw_command"])
        if is_memory_command(raw):
            continue
        try:
            dow, bucket = parse_local_context(str(row["executed_at"]))
        except ValueError:
            continue
        key = (dow, bucket, raw)
        entry = grouped.setdefault(
            key,
            {
                "day_of_week": dow,
                "hour_bucket": bucket,
                "key": raw,
                "total": 0,
                "days": set(),
            },
        )
        entry["total"] += 1
        entry["days"].add(str(row["executed_at"])[:10])

    return [
        {
            "day_of_week": item["day_of_week"],
            "hour_bucket": item["hour_bucket"],
            "key": item["key"],
            "total": item["total"],
            "distinct_days": len(item["days"]),
        }
        for item in grouped.values()
    ]


def get_repeated_commands(min_count: int = 3, limit: int = 10) -> list[dict[str, Any]]:
    """Comandos repetidos manualmente (candidatos a virar workflow)."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT raw_command, COUNT(*) AS total FROM command_history "
            "WHERE success = 1 GROUP BY raw_command "
            "HAVING COUNT(*) >= ? ORDER BY total DESC LIMIT ?",
            (max(1, int(min_count)), max(1, min(int(limit), 50))),
        ).fetchall()
    return [
        {"raw_command": str(row["raw_command"]), "total": int(row["total"])}
        for row in rows
        if not is_memory_command(str(row["raw_command"]))
    ]


# ---------------------------------------------------------------------------
# Perfil de interesses (user_interests) com decaimento temporal
# ---------------------------------------------------------------------------


def upsert_interest(category: str, keyword: str, *, weight_delta: float = 1.0) -> None:
    """Incrementa o peso aplicando decaimento desde a ultima observacao.

    Meia-vida de 45 dias: um gosto de ~6 meses pesa ~1/16 do atual. Assim
    interesses recentes dominam sem apagar o historico.
    """
    category = category.strip().lower()
    keyword = keyword.strip().lower()
    if not category or not keyword:
        return
    now = datetime.now(UTC)
    with _connect() as conn:
        row = conn.execute(
            "SELECT weight, last_seen FROM user_interests WHERE category = ? AND keyword = ?",
            (category, keyword),
        ).fetchone()
        if row is None:
            weight = max(0.0, float(weight_delta))
        else:
            try:
                last = datetime.fromisoformat(str(row["last_seen"]))
                if last.tzinfo is None:
                    last = last.replace(tzinfo=UTC)
                age_days = max(0.0, (now - last).total_seconds() / 86400.0)
            except (ValueError, TypeError):
                age_days = 0.0
            decayed = float(row["weight"]) * 0.5 ** (age_days / _INTEREST_HALF_LIFE_DAYS)
            weight = decayed + max(0.0, float(weight_delta))
        conn.execute(
            "INSERT INTO user_interests (category, keyword, weight, last_seen) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(category, keyword) DO UPDATE SET "
            "weight = excluded.weight, last_seen = excluded.last_seen",
            (category, keyword, weight, now.isoformat(timespec="seconds")),
        )


def get_interest_profile(limit: int = 10) -> list[dict[str, Any]]:
    """Interesses ordenados pelo peso efetivo (ja com decaimento por idade)."""
    now = datetime.now(UTC)
    with _connect() as conn:
        rows = conn.execute(
            "SELECT category, keyword, weight, last_seen FROM user_interests"
        ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        try:
            last = datetime.fromisoformat(str(row["last_seen"]))
            if last.tzinfo is None:
                last = last.replace(tzinfo=UTC)
            age_days = max(0.0, (now - last).total_seconds() / 86400.0)
        except (ValueError, TypeError):
            age_days = 0.0
        stored = float(row["weight"])
        result.append(
            {
                "category": str(row["category"]),
                "keyword": str(row["keyword"]),
                "weight": round(stored, 3),
                "effective_weight": round(stored * 0.5 ** (age_days / _INTEREST_HALF_LIFE_DAYS), 3),
                "last_seen": str(row["last_seen"]),
            }
        )
    result.sort(key=lambda item: item["effective_weight"], reverse=True)
    return result[: max(1, min(int(limit), 100))]


# ---------------------------------------------------------------------------
# Rotinas aprendidas (learned_routines) + cooldown
# ---------------------------------------------------------------------------


def upsert_routine(
    trigger_context: str,
    suggested_actions: list[str],
    confidence: float,
    times_observed: int,
) -> None:
    payload = json.dumps(suggested_actions, ensure_ascii=False)
    with _connect() as conn:
        conn.execute(
            "INSERT INTO learned_routines "
            "(trigger_context, suggested_actions, confidence, times_observed, last_suggested) "
            "VALUES (?, ?, ?, ?, NULL) "
            "ON CONFLICT(trigger_context) DO UPDATE SET "
            "suggested_actions = excluded.suggested_actions, "
            "confidence = excluded.confidence, "
            "times_observed = excluded.times_observed",
            (trigger_context, payload, float(confidence), int(times_observed)),
        )


def get_routines(min_confidence: float = 0.0) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, trigger_context, suggested_actions, confidence, "
            "times_observed, last_suggested FROM learned_routines "
            "WHERE confidence >= ? ORDER BY confidence DESC, times_observed DESC",
            (float(min_confidence),),
        ).fetchall()
    result = []
    for row in rows:
        try:
            actions = json.loads(str(row["suggested_actions"] or "[]"))
        except json.JSONDecodeError:
            actions = []
        result.append(
            {
                "id": int(row["id"]),
                "trigger_context": str(row["trigger_context"]),
                "suggested_actions": list(actions),
                "confidence": float(row["confidence"]),
                "times_observed": int(row["times_observed"]),
                "last_suggested": row["last_suggested"],
            }
        )
    return result


def mark_routine_suggested(trigger_context: str) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE learned_routines SET last_suggested = ? WHERE trigger_context = ?",
            (_utcnow(), trigger_context),
        )


def get_meta(key: str) -> str | None:
    with _connect() as conn:
        row = conn.execute("SELECT value FROM app_meta WHERE key = ?", (key,)).fetchone()
    return str(row["value"]) if row is not None else None


def set_meta(key: str, value: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO app_meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def purge_observer_data() -> None:
    """Apaga TUDO que o observador/learner aprenderam (controle de privacidade)."""
    with _connect() as conn:
        conn.execute("DELETE FROM activity_events")
        conn.execute("DELETE FROM user_interests")
        conn.execute("DELETE FROM learned_routines")
        conn.execute("DELETE FROM app_meta")
