"""Mensajes del equipo por caso: acceso, cifrado, avisos automáticos, no leídos y notificaciones."""
import io

import pytest

from helpers import CSRF, _client_as, _web_app, add_case, add_user, admin_id, supervise
from vexa.security import vault


@pytest.fixture
def firm(monkeypatch, tmp_path):
    web = _web_app(monkeypatch, tmp_path)
    ids = {"admin": admin_id(web), "chief": add_user(web, "jefa", "chief_lawyer", "Carla Jefa"),
           "lawyer": add_user(web, "luis", name="Luis Soto"), "other": add_user(web, "otra", name="Otra")}
    supervise(web, ids["chief"], ids["lawyer"])
    ids["case"] = add_case(web, ids["admin"], user_id=ids["lawyer"], title="Despido injustificado")
    return web, ids


def _send(client, case_id, body, ajax=True):
    headers = {"X-Requested-With": "vexa-fetch"} if ajax else {}
    return client.post(f"/case/{case_id}/mensajes", data={"csrf_token": CSRF, "body": body}, headers=headers)


def test_team_conversation_between_lawyer_chief_and_admin(firm):
    web, ids = firm
    case = ids["case"]
    lawyer, chief, admin = (_client_as(web, ids[k]) for k in ("lawyer", "chief", "admin"))
    response = _send(lawyer, case, "Faltan documentos: el contrato firmado.")
    assert response.get_json()["ok"] and response.get_json()["messages"][-1]["mine"] is True
    with web.connect_db() as db:
        stored = db.execute("SELECT body FROM case_messages").fetchone()[0]
    assert stored.startswith(vault.TEXT_PREFIX) and "contrato" not in stored          # cifrado en la base

    # Jefe a cargo y quien creó el caso reciben una sola notificación aunque lleguen varios mensajes.
    _send(lawyer, case, "Y también el anexo.")
    with web.connect_db() as db:
        notes = {r[0]: r[1] for r in db.execute(
            "SELECT user_id, COUNT(*) FROM notifications WHERE kind = 'mensaje' GROUP BY user_id")}
    assert notes == {ids["chief"]: 1, ids["admin"]: 1}

    data = chief.get(f"/api/case/{case}/mensajes").get_json()
    assert [m["body"] for m in data["messages"]] == ["Faltan documentos: el contrato firmado.", "Y también el anexo."]
    assert data["unread"] == 2
    chief.get(f"/api/case/{case}/mensajes?read=1")
    assert chief.get(f"/api/case/{case}/mensajes").get_json()["unread"] == 0
    with web.connect_db() as db:
        assert db.execute("SELECT read_at FROM notifications WHERE user_id = ? AND kind = 'mensaje'",
                          (ids["chief"],)).fetchone()[0] is not None                  # leer la conversación la marca

    _send(admin, case, "Ya subí el contrato.", ajax=False)
    inbox = lawyer.get("/mensajes").get_data(as_text=True)
    assert "Despido injustificado" in inbox and "Ya subí el contrato." in inbox
    page = lawyer.get(f"/case/{case}").get_data(as_text=True)
    assert 'data-panel-tab="mensajes"' in page and "Faltan documentos" in page and "js/case-messages.js" in page


def test_people_without_access_cannot_read_or_write(firm):
    web, ids = firm
    other = _client_as(web, ids["other"])
    assert _send(other, ids["case"], "hola").status_code == 403
    assert other.get(f"/api/case/{ids['case']}/mensajes").status_code == 403
    assert "Despido injustificado" not in other.get("/mensajes").get_data(as_text=True)
    with web.connect_db() as db:
        db.execute("INSERT INTO user_permissions(user_id, permission, effect) VALUES (?, 'cases.message', 'deny')",
                   (ids["lawyer"],))
    assert _send(_client_as(web, ids["lawyer"]), ids["case"], "hola").status_code == 403


def test_events_leave_automatic_notices_without_revealing_documents(firm):
    web, ids = firm
    admin = _client_as(web, ids["admin"])
    admin.post(f"/case/{ids['case']}/documents", data={"csrf_token": CSRF, "restricted": "1",
               "documents": (io.BytesIO(b"x"), "informe_secreto.txt")}, content_type="multipart/form-data")
    admin.post(f"/admin/cases/{ids['case']}/due", data={"csrf_token": CSRF, "due_at": "2099-06-01T10:00"})
    admin.post(f"/case/{ids['case']}/progress", data={"csrf_token": CSRF, "status": "cerrado", "progress": "40",
                                                      "close_reason": "abandono"})
    bodies = [m["body"] for m in _client_as(web, ids["lawyer"]).get(f"/api/case/{ids['case']}/mensajes").get_json()["messages"]]
    assert any("agregó 1 documento(s)" in b for b in bodies)
    assert any("amplió la fecha límite: 01-01-2099 00:00 → 01-06-2099 10:00" in b for b in bodies)
    assert any("Cerrado · Abandono, 40 %" in b for b in bodies)
    assert not any("informe_secreto" in b for b in bodies)                          # sin nombres de documentos


def test_empty_or_long_messages_are_rejected(firm):
    web, ids = firm
    lawyer = _client_as(web, ids["lawyer"])
    assert _send(lawyer, ids["case"], "   ").status_code == 400
    assert _send(lawyer, ids["case"], "x" * 2001).status_code == 400
    with web.connect_db() as db:
        assert db.execute("SELECT COUNT(*) FROM case_messages").fetchone()[0] == 0
