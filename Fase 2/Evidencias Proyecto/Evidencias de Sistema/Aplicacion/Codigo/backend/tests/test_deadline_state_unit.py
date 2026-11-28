"""Pruebas unitarias del semáforo de plazos de los casos."""
from datetime import datetime

from vexa.services.cases import deadline_state

NOW = datetime(2026, 11, 1, 12, 0)


def test_closed_cases_do_not_run_deadlines():
    assert deadline_state("2020-01-01T10:00", "cerrado", now=NOW) == "cerrado"


def test_past_deadline_is_overdue():
    assert deadline_state("2026-10-31T23:59", "en_curso", now=NOW) == "vencido"
