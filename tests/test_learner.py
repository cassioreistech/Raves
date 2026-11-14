from datetime import datetime, timedelta

from winbot.core import database
from winbot.core.learner import GREETING_CONFIDENCE, BehaviorLearner, context_key


def _seed_routine(raw: str = "abrir calc", occurrences: int = 3) -> None:
    """Insere comandos no MESMO dia da semana/faixa, em semanas diferentes."""
    local_now = datetime.now().astimezone()
    tz = local_now.tzinfo
    hour = {"manha": 9, "tarde": 14, "noite": 20, "madrugada": 2}[
        database.hour_bucket_for(local_now.hour)
    ]
    with database._connect() as conn:
        for weeks in range(occurrences):
            day = (local_now - timedelta(weeks=weeks)).date()
            moment = datetime(day.year, day.month, day.day, hour, 0, tzinfo=tz)
            conn.execute(
                "INSERT INTO command_history "
                "(raw_command, success, result_message, executed_at) "
                "VALUES (?, 1, 'OK', ?)",
                (raw, moment.isoformat(timespec="seconds")),
            )


def test_analyze_patterns_respeita_minimo_de_ocorrencias() -> None:
    _seed_routine(occurrences=2)
    assert BehaviorLearner().analyze_patterns() == 0
    assert database.get_routines() == []


def test_analyze_patterns_consolida_com_confianca_alta() -> None:
    _seed_routine(occurrences=3)
    assert BehaviorLearner().analyze_patterns() >= 1
    routines = database.get_routines()
    assert routines
    assert routines[0]["times_observed"] >= 3
    assert routines[0]["confidence"] >= GREETING_CONFIDENCE
    assert "abrir calc" in routines[0]["suggested_actions"]


def test_get_proactive_greeting_com_cooldown() -> None:
    _seed_routine(occurrences=3)
    learner = BehaviorLearner()
    learner.analyze_patterns()

    greeting = learner.get_proactive_greeting()
    assert greeting is not None
    assert "Quer que eu prepare o ambiente agora?" in greeting
    # Cooldown global de 6h: segunda chamada nao repete.
    assert learner.get_proactive_greeting() is None


def test_cooldown_bloqueia_mesmo_com_rotina_valida() -> None:
    _seed_routine(occurrences=3)
    BehaviorLearner().analyze_patterns()
    database.set_meta("last_proactive_greeting", database._utcnow())
    assert BehaviorLearner().get_proactive_greeting() is None


def test_get_recommendations_inclui_interesses_e_workflows() -> None:
    database.upsert_interest("musica", "lofi")
    _seed_routine(occurrences=3)
    BehaviorLearner().analyze_patterns()

    tips = BehaviorLearner().get_recommendations()
    assert any("lofi" in tip for tip in tips)
    assert any("workflow" in tip for tip in tips)


def test_decaimento_de_interesse() -> None:
    database.upsert_interest("musica", "lofi", weight_delta=10.0)
    with database._connect() as conn:
        conn.execute(
            "UPDATE user_interests SET last_seen = ? WHERE category = 'musica'",
            ("2020-01-01T00:00:00+00:00",),
        )
    profile = database.get_interest_profile()[0]
    assert profile["effective_weight"] < 0.01
    assert profile["weight"] == 10.0  # historico bruto preservado


def test_context_key_roundtrip() -> None:
    from winbot.core.learner import parse_context

    key = context_key(4, "tarde")
    assert parse_context(key) == (4, "tarde")
