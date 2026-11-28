"""Calendario de vencimientos: vista mensual y solo casos dentro del alcance de cada persona."""
from datetime import date

import pytest

from helpers import _client_as, _web_app, add_case, add_user, admin_id
from vexa.services import calendar as calendar_service


def test_parse_month_and_navigation():
    today = date(2026, 11, 27)
    assert calendar_service.parse_month("2027-02", today) == (2027, 2)
    assert calendar_service.parse_month("basura", today) == (2026, 11)
    assert calendar_service.parse_month("2026-13", today) == (2026, 11)
    assert calendar_service.shift(2026, 12, 1) == "2027-01"
    assert calendar_service.shift(2026, 1, -1) == "2025-12"


def test_month_view_places_cases_on_their_day():
    cases = [{"id": 1, "title": "Vence", "due_at": "2026-11-05T18:00", "status": "en_curso"},
             {"id": 2, "title": "Otro mes", "due_at": "2026-12-01T09:00", "status": "en_curso"},
             {"id": 3, "title": "Cerrado", "due_at": "2026-11-05T09:00", "status": "cerrado"}]
    view = calendar_service.month_view(cases, 2026, 11, today=date(2026, 11, 5))
    assert view["label"] == "Noviembre 2026" and view["total"] == 2
    days = {cell["day"]: cell for week in view["weeks"] for cell in week if cell}
    assert [c["title"] for c in days[5]["cases"]] == ["Cerrado", "Vence"]       # ordenados por hora
    assert days[5]["today"] and days[5]["cases"][0]["state"] == "cerrado"
    assert view["weeks"][0][0] is None                                          # 1-nov-2026 es domingo
    assert all(len(week) == 7 for week in view["weeks"])


@pytest.fixture
def web(monkeypatch, tmp_path):
    web = _web_app(monkeypatch, tmp_path)
    a = admin_id(web)
    luis, ana = add_user(web, "luis"), add_user(web, "ana")
    mine = add_case(web, a, user_id=luis, title="Caso de Luis")
    other = add_case(web, a, user_id=ana, title="Caso de Ana")
    with web.connect_db() as db:
        db.executemany("UPDATE cases SET due_at = '2099-03-10T12:00' WHERE id = ?", [(mine,), (other,)])
    return web, luis


def test_calendar_page_shows_only_cases_in_scope(web):
    web, luis = web
    html = _client_as(web, luis).get("/calendario?mes=2099-03").get_data(as_text=True)
    assert "Marzo 2099" in html and "Caso de Luis" in html
    assert "Caso de Ana" not in html
    assert 'href="/calendario?mes=2099-02"' in html and 'href="/calendario?mes=2099-04"' in html
    assert "Caso de Luis" not in _client_as(web, luis).get("/calendario?mes=2099-04").get_data(as_text=True)


def test_calendar_requires_login(web):
    web, _ = web
    assert web.app.test_client().get("/calendario").status_code == 302
