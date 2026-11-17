"""Notificaciones: eventos, destinatarios con acceso, recordatorios sin repetir y campana."""
import io
from datetime import datetime, timedelta

import pytest

from helpers import CSRF, _client_as, _web_app, add_case, add_user, admin_id, supervise
from vexa.services import notifications


@pytest.fixture
def firm(monkeypatch, tmp_path):
    web = _web_app(monkeypatch, tmp_path)
    ids = {"admin": admin_id(web), "chief": add_user(web, "jefa", "chief_lawyer", "Carla Jefa"),
           "lawyer": add_user(web, "luis", name="Luis Soto"), "other": add_user(web, "otra", name="Otra Abogada")}
    supervise(web, ids["chief"], ids["lawyer"])
    return web, ids


def _titles(web, user_id):
    with web.connect_db() as db:
        return [r[0] for r in db.execute("SELECT title FROM notifications WHERE user_id = ? ORDER BY id", (user_id,))]


def _new_case(client, assignee, title="Despido injustificado"):
    return client.post("/admin/cases", data={
        "csrf_token": CSRF, "title": title, "summary": "Resumen", "due_at": "2099-01-01T10:00",
        "assignment_type": "user", "assignee_id": str(assignee),
        "documents": (io.BytesIO(b"Texto."), "caso.txt")}, content_type="multipart/form-data")


def test_case_lifecycle_notifies_the_right_people(firm):
    web, ids = firm
    admin = _client_as(web, ids["admin"])
    _new_case(admin, ids["lawyer"])
    with web.connect_db() as db:
        case_id = db.execute("SELECT id FROM cases").fetchone()[0]
    assert _titles(web, ids["lawyer"]) == ["Te asignaron el caso «Despido injustificado»."]
    assert _titles(web, ids["other"]) == []                     # no es responsable ni lo ve

    _client_as(web, ids["lawyer"]).post(f"/case/{case_id}/notes", data={"csrf_token": CSRF, "note": "Avancé"})
    assert "Luis Soto registró una nota en «Despido injustificado»." in _titles(web, ids["chief"])   # jefe a cargo
    assert "Luis Soto registró una nota en «Despido injustificado»." in _titles(web, ids["admin"])   # creó el caso
    assert not any("nota" in t for t in _titles(web, ids["lawyer"]))                                # no a sí mismo

    admin.post(f"/case/{case_id}/progress", data={"csrf_token": CSRF, "status": "en_revision", "progress": "60"})
    admin.post(f"/admin/cases/{case_id}/due", data={"csrf_token": CSRF, "due_at": "2099-03-01T09:30"})
    admin.post(f"/case/{case_id}/documents", data={"csrf_token": CSRF, "documents": (io.BytesIO(b"x"), "anexo.txt")},
               content_type="multipart/form-data")
    lawyer = _titles(web, ids["lawyer"])
    assert "Avance de «Despido injustificado»: En revisión, 60 %." in lawyer
    assert "Nueva fecha límite para «Despido injustificado»: 01-03-2099 09:30." in lawyer
    assert "Se agregaron 1 documento(s) a «Despido injustificado»." in lawyer
    assert "texto privado" not in " ".join(lawyer)


def test_never_notifies_someone_who_cannot_see_the_case(firm):
    web, ids = firm
    case_id = add_case(web, ids["admin"], user_id=ids["lawyer"], title="Reservado")
    created = notifications.notify(web.settings.db_path, [ids["other"], ids["lawyer"]], "avance", "Aviso", case_id=case_id)
    assert created == 1 and _titles(web, ids["other"]) == []


def test_deadline_reminders_are_sent_once_per_due_date(firm):
    web, ids = firm
    soon = add_case(web, ids["admin"], user_id=ids["lawyer"], title="Pronto")
    late = add_case(web, ids["admin"], user_id=ids["lawyer"], title="Atrasado")
    add_case(web, ids["admin"], user_id=ids["lawyer"], title="Holgado")
    fmt = "%Y-%m-%dT%H:%M"
    with web.connect_db() as db:
        db.execute("UPDATE cases SET due_at = ? WHERE id = ?", ((datetime.now() + timedelta(days=2)).strftime(fmt), soon))
        db.execute("UPDATE cases SET due_at = ? WHERE id = ?", ((datetime.now() - timedelta(days=1)).strftime(fmt), late))
    first = notifications.check_deadlines(web.settings.db_path)
    again = notifications.check_deadlines(web.settings.db_path)
    assert first == 4 and again == 0                 # abogado + jefe a cargo, sin repetir
    titles = _titles(web, ids["lawyer"])
    assert any(t.startswith("El caso «Pronto» vence el") for t in titles)
    assert any(t.startswith("El caso «Atrasado» venció el") for t in titles)
    assert not any("Holgado" in t for t in titles)


def test_bell_page_and_reading(firm):
    web, ids = firm
    case_id = add_case(web, ids["admin"], user_id=ids["lawyer"], title="Arriendo")
    notifications.notify(web.settings.db_path, [ids["lawyer"]], "asignacion", "Te asignaron el caso «Arriendo».",
                         case_id=case_id)
    lawyer = _client_as(web, ids["lawyer"])
    home = lawyer.get("/lawyer").get_data(as_text=True)
    assert 'class="notif-bell"' in home and "data-notif-badge >1<" in home
    assert lawyer.get("/api/notificaciones/contador").get_json() == {"unread": 1}
    page = lawyer.get("/notificaciones").get_data(as_text=True)
    assert "Te asignaron el caso «Arriendo»." in page and "is-unread" in page
    with web.connect_db() as db:
        nid = db.execute("SELECT id FROM notifications").fetchone()[0]
    assert lawyer.get(f"/notificaciones/{nid}").headers["Location"].endswith(f"/case/{case_id}")
    assert lawyer.get("/api/notificaciones/contador").get_json() == {"unread": 0}
    # Nadie abre ni marca avisos de otra persona.
    assert _client_as(web, ids["other"]).get(f"/notificaciones/{nid}").headers["Location"].endswith("/notificaciones")
