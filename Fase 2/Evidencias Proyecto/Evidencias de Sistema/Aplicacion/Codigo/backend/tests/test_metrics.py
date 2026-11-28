"""Administración > Métricas: indicadores del estudio, solo metadatos y solo para el administrador."""
import pytest

from helpers import _client_as, _web_app, add_case, add_user, admin_id
from vexa.services import metrics


@pytest.fixture
def web(monkeypatch, tmp_path):
    web = _web_app(monkeypatch, tmp_path)
    a = admin_id(web)
    luis, ana = add_user(web, "luis", name="Luis"), add_user(web, "ana", name="Ana")
    with web.connect_db() as db:
        team = db.execute("INSERT INTO teams(name) VALUES ('Laboral')").lastrowid
        db.executemany("INSERT INTO team_members(team_id, user_id) VALUES (?, ?)", [(team, luis), (team, ana)])
    late = add_case(web, a, user_id=luis, title="Caso vencido secreto")
    add_case(web, a, team_id=team, title="Caso del equipo")
    closed = add_case(web, a, user_id=ana, title="Caso cerrado")
    with web.connect_db() as db:
        db.execute("UPDATE cases SET due_at = '2020-01-01T00:00' WHERE id = ?", (late,))
        db.execute("UPDATE cases SET status = 'cerrado', created_at = '2026-01-01 10:00:00' WHERE id = ?", (closed,))
        db.execute("INSERT INTO case_updates(case_id, user_id, status, progress, created_at) "
                   "VALUES (?, ?, 'cerrado', 100, '2026-01-11 10:00:00')", (closed, a))
    return web, {"admin": a, "luis": luis, "ana": ana}


def test_firm_metrics_counts_states_close_time_and_workload(web):
    web, _ = web
    data = metrics.firm_metrics(web.db_path)
    assert (data["total"], data["open"], data["overdue"]) == (3, 2, 1)
    assert data["avg_close_days"] == 10.0 and data["closed_count"] == 1
    assert {s["key"]: s["count"] for s in data["by_status"]}["cerrado"] == 1
    load = {p["name"]: p for p in data["workload"]}
    assert load["Luis"]["open"] == 2 and load["Luis"]["overdue"] == 1    # directo + equipo
    assert load["Ana"]["open"] == 1                                       # el cerrado no cuenta
    assert load["Luis"]["share"] == 100 and load["Ana"]["share"] == 50


def test_metrics_tab_is_admin_only_and_shows_no_case_titles(web):
    web, ids = web
    html = _client_as(web, ids["admin"]).get("/admin?tab=metricas").get_data(as_text=True)
    assert "Métricas del estudio" in html and "10.0 días" in html
    panel = html.split('id="tab-metricas"')[1].split("</section>")[0]
    assert "Caso vencido secreto" not in panel                           # solo metadatos
    chief = add_user(web, "jefa", "chief_lawyer")
    assert 'id="tab-metricas"' not in _client_as(web, chief).get("/admin?tab=metricas").get_data(as_text=True)


def test_metrics_with_no_cases(monkeypatch, tmp_path):
    web = _web_app(monkeypatch, tmp_path)
    data = metrics.firm_metrics(web.db_path)
    assert (data["total"], data["avg_close_days"], data["workload"]) == (0, None, [])
    assert all(s["share"] == 0 for s in data["by_status"])
    assert "—" in _client_as(web, admin_id(web)).get("/admin?tab=metricas").get_data(as_text=True)
