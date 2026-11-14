"""Motor de aprendizado e recomendação 100% offline.

Só SQL + estatística de frequência sobre ``command_history`` e
``activity_events``. Nenhum modelo, nenhuma rede, nenhuma API externa.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from raves.core import database

MIN_OCCURRENCES = 3
GREETING_CONFIDENCE = 0.75
COOLDOWN_HOURS = 6.0
_GREETING_META_KEY = "last_proactive_greeting"

_WEEKDAYS = ("segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo")
_BUCKET_SAUDACAO = {
    "manha": "Bom dia",
    "tarde": "Boa tarde",
    "noite": "Boa noite",
    "madrugada": "Oi",
}


def context_key(day_of_week: int, hour_bucket: str) -> str:
    """Chave canônica de um contexto temporal, usada em learned_routines."""
    return f"dow={day_of_week};bucket={hour_bucket}"


def parse_context(key: str) -> tuple[int, str]:
    parts = dict(part.split("=", 1) for part in key.split(";") if "=" in part)
    try:
        dow = int(parts.get("dow", 0))
    except ValueError:
        dow = 0
    return dow, parts.get("bucket", "manha")


def _age_hours(iso_timestamp: str) -> float:
    try:
        moment = datetime.fromisoformat(iso_timestamp)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        return max(0.0, (datetime.now(UTC) - moment).total_seconds() / 3600.0)
    except (ValueError, TypeError):
        return COOLDOWN_HOURS + 1.0


class BehaviorLearner:
    """Consolida rotinas, gera saudação proativa e recomendações."""

    def analyze_patterns(self) -> int:
        """Detecta recorrências >= 3 por (dia, faixa) e salva learned_routines.

        Confiança = ``min(0.95, 0.45 + 0.12 * dias_distintos)``: 3 dias distintos
        já passam de 75%, 4 chegam a ~93%. Explicável e ajustável sem ML.
        """
        groups: dict[str, dict[str, Any]] = {}

        def ensure(key: str) -> dict[str, Any]:
            return groups.setdefault(key, {"total": 0, "days": 1, "actions": []})

        for row in database.get_command_context_counts():
            entry = ensure(context_key(row["day_of_week"], row["hour_bucket"]))
            entry["total"] += row["total"]
            entry["days"] = max(entry["days"], row["distinct_days"])
            entry["actions"].append((row["total"], row["key"]))

        for row in database.get_activity_context_counts():
            entry = ensure(context_key(row["day_of_week"], row["hour_bucket"]))
            entry["total"] += row["total"]
            entry["days"] = max(entry["days"], row["distinct_days"])
            label = str(row["app_name"] or row["category"] or "app")
            entry["actions"].append((row["total"], label))

        saved = 0
        for key, entry in groups.items():
            if entry["total"] < MIN_OCCURRENCES:
                continue
            confidence = min(0.95, 0.45 + 0.12 * entry["days"])
            ranked = sorted(entry["actions"], key=lambda item: -item[0])
            actions = list(dict.fromkeys(label for _, label in ranked))[:5]
            database.upsert_routine(key, actions, confidence, entry["total"])
            saved += 1
        return saved

    def _cooldown_active(self) -> bool:
        last = database.get_meta(_GREETING_META_KEY)
        return bool(last) and _age_hours(last) < COOLDOWN_HOURS

    def get_proactive_greeting(self) -> str | None:
        """Sugestão contextual na abertura, com cooldown global de 6 horas.

        Só dispara para confiança > 75%, >= 3 observações, contexto atual e
        rotina não sugerida recentemente. Nunca executa nada sozinha.
        """
        if self._cooldown_active():
            return None
        now = datetime.now().astimezone()
        current = context_key(now.weekday(), database.hour_bucket_for(now.hour))
        routines = database.get_routines(min_confidence=GREETING_CONFIDENCE)
        match = next(
            (
                item
                for item in routines
                if item["trigger_context"] == current and item["times_observed"] >= MIN_OCCURRENCES
            ),
            None,
        )
        if match is None:
            return None
        if match["last_suggested"] and _age_hours(str(match["last_suggested"])) < COOLDOWN_HOURS:
            return None

        dow, bucket = parse_context(match["trigger_context"])
        interests = database.get_interest_profile(limit=3)
        profile = ", ".join(f"{item['keyword']} ({item['category']})" for item in interests)
        actions = ", ".join(match["suggested_actions"][:3]) or "suas tarefas habituais"

        text = (
            f"{_BUCKET_SAUDACAO[bucket]}! Às {bucket} de {_WEEKDAYS[dow]} você costuma "
            f"usar {actions}."
        )
        if profile:
            text += f" Seu perfil recente aponta {profile}."
        text += " Quer que eu prepare o ambiente agora?"

        database.set_meta(_GREETING_META_KEY, datetime.now(UTC).isoformat(timespec="seconds"))
        database.mark_routine_suggested(current)
        return text

    def get_recommendations(self) -> list[str]:
        """Dicas personalizadas: interesses, comandos repetidos e rotinas."""
        tips: list[str] = []
        interests = database.get_interest_profile(limit=5)
        if not interests:
            tips.append(
                "Ainda não aprendi nada sobre você. Use o RAVES por alguns dias e "
                "rode 'raves insights suggest' de novo."
            )
        for item in interests[:3]:
            tips.append(
                f"Interesse '{item['keyword']}' ({item['category']}) com peso "
                f"{item['effective_weight']:.2f}. Posso criar um atalho 'abrir "
                f"{item['keyword']}' se quiser."
            )

        for row in database.get_repeated_commands(min_count=MIN_OCCURRENCES, limit=3):
            tips.append(
                f"Você executou '{row['raw_command']}' {row['total']} vezes. Quer que eu "
                "transforme isso num workflow automático?"
            )

        for routine in database.get_routines(min_confidence=GREETING_CONFIDENCE)[:2]:
            dow, bucket = parse_context(routine["trigger_context"])
            actions = ", ".join(routine["suggested_actions"][:3]) or "suas tarefas"
            tips.append(
                f"Rotina {bucket}/{_WEEKDAYS[dow]} com {routine['confidence']:.0%} de "
                f"confiança: {actions}. Posso sugerir na abertura do shell."
            )
        return tips[:8]
