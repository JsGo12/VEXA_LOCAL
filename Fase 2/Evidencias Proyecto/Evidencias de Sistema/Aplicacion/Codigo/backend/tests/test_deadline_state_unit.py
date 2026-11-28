"""Pruebas unitarias del semáforo de plazos de los casos."""
from datetime import datetime

from vexa.services.cases import deadline_state

NOW = datetime(2026, 11, 1, 12, 0)


def test_closed_cases_do_not_run_deadlines():
    assert deadline_state("2020-01-01T10:00", "cerrado", now=NOW) == "cerrado"


def test_past_deadline_is_overdue():
    assert deadline_state("2026-10-31T23:59", "en_curso", now=NOW) == "vencido"


def test_upcoming_deadline_is_soon_or_on_time():
    assert deadline_state("2026-11-05T10:00", "pendiente", now=NOW) == "pronto"
    assert deadline_state("2026-12-30T10:00", "pendiente", now=NOW) == "al_dia"
    assert deadline_state("2026-11-20T10:00", "pendiente", now=NOW, soon_days=30) == "pronto"


def test_invalid_dates_do_not_break_the_panel():
    for value in ("", None, "mañana", "2026-13-01T10:00"):
        assert deadline_state(value, "pendiente", now=NOW) == "al_dia"
