"""Avance de casos, panel de seguimiento, contraseñas propias y carga de documentos a casos existentes."""
import io
from pathlib import Path

import pytest

from helpers import CSRF, PASSWORD, _client_as, _web_app, add_case, add_document, add_user, admin_id
from vexa.security import vault


@pytest.fixture
def firm(monkeypatch, tmp_path):
    web = _web_app(monkeypatch, tmp_path)
    ids = {"admin": admin_id(web), "lawyer": add_user(web, "luis"), "other": add_user(web, "otra")}
    ids["case"] = add_case(web, ids["admin"], user_id=ids["lawyer"], title="Arriendo")
    add_document(web, ids["case"], ids["admin"], "contrato.txt", b"Contrato.")
    return web, ids


def _token(client):
    with client.session_transaction() as s:
        return s["csrf_token"]


def _post(client, path, **data):
    return client.post(path, data={"csrf_token": CSRF, **data})


# ------------------------------------------------------------------ avance
def test_assigned_lawyer_updates_progress_and_note_is_encrypted(firm):
    web, ids = firm
    client = _client_as(web, ids["lawyer"])
    response = _post(client, f"/case/{ids['case']}/progress", status="en_revision", progress="70",
                     note="Falta la firma del arrendador.")
    assert response.status_code == 302
    with web.connect_db() as db:
        case = db.execute("SELECT status, progress FROM cases WHERE id = ?", (ids["case"],)).fetchone()
        stored = db.execute("SELECT note FROM case_updates").fetchone()[0]
    assert tuple(case) == ("en_revision", 70)
    assert stored.startswith(vault.TEXT_PREFIX) and "firma" not in stored
    page = client.get(f"/case/{ids['case']}").get_data(as_text=True)
    assert "Falta la firma del arrendador." in page and "En revisión" in page


def test_closing_a_case_sets_full_progress_and_invalid_values_are_rejected(firm):
    web, ids = firm
    client = _client_as(web, ids["lawyer"])
    _post(client, f"/case/{ids['case']}/progress", status="cerrado", progress="40")
    _post(client, f"/case/{ids['case']}/progress", status="inventado", progress="10")
    _post(client, f"/case/{ids['case']}/progress", status="en_curso", progress="150")
    with web.connect_db() as db:
        assert tuple(db.execute("SELECT status, progress FROM cases").fetchone()) == ("cerrado", 100)
        assert db.execute("SELECT COUNT(*) FROM case_updates").fetchone()[0] == 1


def test_unassigned_lawyer_cannot_update_progress(firm):
    web, ids = firm
    response = _post(_client_as(web, ids["other"]), f"/case/{ids['case']}/progress", status="cerrado", progress="100")
    assert response.status_code == 403
    with web.connect_db() as db:
        assert db.execute("SELECT status FROM cases").fetchone()[0] == "en_curso"


def test_follow_up_panel_is_for_case_managers_and_shows_progress(firm):
    web, ids = firm
    _post(_client_as(web, ids["lawyer"]), f"/case/{ids['case']}/progress", status="pendiente", progress="20",
          note="nota privada del expediente")
    assert _client_as(web, ids["lawyer"]).get("/admin/seguimiento").status_code == 403
    page = _client_as(web, ids["admin"]).get("/admin/seguimiento")
    assert page.status_code == 200
    text = page.get_data(as_text=True)
    assert "Arriendo" in text and "Pendiente" in text and 'value="20"' in text
    assert "nota privada" not in text                 # el panel muestra metadatos, no notas


def test_follow_up_traffic_light_marks_overdue_soon_and_on_time(firm):
    from datetime import datetime, timedelta
    web, ids = firm
    soon = add_case(web, ids["admin"], user_id=ids["lawyer"], title="Pronto")
    late = add_case(web, ids["admin"], user_id=ids["lawyer"], title="Atrasado")
    closed = add_case(web, ids["admin"], user_id=ids["lawyer"], title="Cerrado viejo")
    fmt = "%Y-%m-%dT%H:%M"
    with web.connect_db() as db:
        db.execute("UPDATE cases SET due_at = ? WHERE id = ?", ((datetime.now() + timedelta(days=2)).strftime(fmt), soon))
        db.execute("UPDATE cases SET due_at = ? WHERE id IN (?, ?)", ((datetime.now() - timedelta(days=1)).strftime(fmt), late, closed))
        db.execute("UPDATE cases SET status = 'cerrado' WHERE id = ?", (closed,))
    data = __import__("vexa.services.cases", fromlist=["follow_up"]).follow_up(web.settings.db_path)
    state = {c["title"]: c["deadline_state"] for c in data["cases"]}
    assert state == {"Arriendo": "al_dia", "Pronto": "pronto", "Atrasado": "vencido", "Cerrado viejo": "al_dia"}
    text = _client_as(web, ids["admin"]).get("/admin/seguimiento").get_data(as_text=True)
    assert 'class="deadline-vencido"' in text and 'class="deadline-pronto"' in text and 'class="deadline-al_dia"' in text


def test_only_admin_changes_due_date_and_it_is_audited(firm):
    from helpers import grant
    web, ids = firm
    chief = add_user(web, "jefa", role="chief_lawyer")
    grant(web, chief, "firm")
    path = f"/admin/cases/{ids['case']}/due"
    # El abogado jefe ve el seguimiento pero no puede cambiar plazos (ni ve el formulario).
    chief_client = _client_as(web, chief)
    assert 'name="due_at"' not in chief_client.get("/admin/seguimiento").get_data(as_text=True)
    assert _post(chief_client, path, due_at="2099-06-01T10:00").status_code == 403
    assert _post(_client_as(web, ids["lawyer"]), path, due_at="2099-06-01T10:00").status_code == 403
    admin = _client_as(web, ids["admin"])
    assert 'name="due_at"' in admin.get("/admin/seguimiento").get_data(as_text=True)
    assert _post(admin, path, due_at="2000-01-01T10:00").status_code == 302     # pasada: se rechaza
    assert _post(admin, path, due_at="no-es-fecha").status_code == 302
    with web.connect_db() as db:
        assert db.execute("SELECT due_at FROM cases WHERE id = ?", (ids["case"],)).fetchone()[0] == "2099-01-01T00:00"
    response = _post(admin, path, due_at="2099-06-01T10:00")
    assert response.status_code == 302 and response.headers["Location"].endswith("/admin/seguimiento")
    with web.connect_db() as db:
        assert db.execute("SELECT due_at FROM cases WHERE id = ?", (ids["case"],)).fetchone()[0] == "2099-06-01T10:00"
        rows = db.execute("SELECT result FROM audit_log WHERE action = 'cases.due_date_change'").fetchall()
    assert [r[0] for r in rows].count("ok") == 1 and [r[0] for r in rows].count("denied") == 2


# --------------------------------------------------------------- contraseñas
def test_new_accounts_must_change_their_temporary_password(firm):
    web, ids = firm
    admin = _client_as(web, ids["admin"])
    _post(admin, "/admin/users", name="Nueva", username="nueva", password="Temporal12345", role="lawyer")
    client = web.app.test_client()
    with client.session_transaction() as s:
        s["csrf_token"] = CSRF
    client.post("/login", data={"username": "nueva", "password": "Temporal12345", "csrf_token": CSRF})
    assert client.get("/lawyer").headers["Location"].endswith("/account/password")
    assert client.get("/api/ollama/status").status_code == 403
    response = client.post("/account/password", data={"csrf_token": _token(client), "current_password": "Temporal12345",
                                                      "new_password": "MiClaveNueva123", "confirm_password": "MiClaveNueva123"})
    assert response.status_code == 302
    with client.session_transaction() as s:
        token = s["csrf_token"]
    assert token != CSRF
    assert client.get("/lawyer").status_code == 200


def test_password_change_requires_current_password_and_logs_out_other_sessions(firm):
    web, ids = firm
    first = web.app.test_client()
    second = web.app.test_client()
    for c in (first, second):
        with c.session_transaction() as s:
            s["csrf_token"] = CSRF
        c.post("/login", data={"username": "luis", "password": PASSWORD, "csrf_token": CSRF})
        assert c.get("/lawyer").status_code == 200
    bad = first.post("/account/password", data={"csrf_token": _token(first), "current_password": "incorrecta",
                                                 "new_password": "OtraClave12345", "confirm_password": "OtraClave12345"})
    assert b"no es correcta" in bad.data
    with first.session_transaction() as s:
        token = s["csrf_token"]
    first.post("/account/password", data={"csrf_token": token, "current_password": PASSWORD,
                                          "new_password": "OtraClave12345", "confirm_password": "OtraClave12345"})
    assert first.get("/lawyer").status_code == 200          # la sesión que cambió la clave sigue
    assert second.get("/lawyer").status_code == 302          # la otra sesión se cerró
    with web.connect_db() as db:
        rows = db.execute("SELECT details FROM audit_log WHERE action = 'auth.password_change'").fetchall()
    assert rows and all("OtraClave" not in (r[0] or "") for r in rows)


def test_admin_reset_password_forces_change_and_chief_cannot_reset_admin(firm):
    web, ids = firm
    _post(_client_as(web, ids["admin"]), f"/admin/users/{ids['lawyer']}/password", password="Temporal99999")
    with web.connect_db() as db:
        assert db.execute("SELECT must_change_password FROM users WHERE id = ?", (ids["lawyer"],)).fetchone()[0] == 1
    assert _client_as(web, ids["lawyer"]).get("/lawyer").status_code == 302     # sesión anterior invalidada
    chief = add_user(web, "jefa", "chief_lawyer")
    _post(_client_as(web, chief), f"/admin/users/{ids['admin']}/password", password="Hackeo123456")
    with web.connect_db() as db:
        assert db.execute("SELECT must_change_password FROM users WHERE id = ?", (ids["admin"],)).fetchone()[0] == 0


def test_initial_admin_with_generated_password_must_change_it(monkeypatch, tmp_path):
    web = _web_app(monkeypatch, tmp_path)
    uid = admin_id(web, pending_password_change=True)
    with web.connect_db() as db:
        assert db.execute("SELECT must_change_password FROM users WHERE id = ?", (uid,)).fetchone()[0] == 1


# ----------------------------------------------------------- carga de documentos
def test_admin_uploads_documents_to_existing_case_encrypted(firm):
    web, ids = firm
    response = _client_as(web, ids["admin"]).post(
        f"/case/{ids['case']}/documents", content_type="multipart/form-data",
        data={"csrf_token": CSRF, "documents": (io.BytesIO(b"Anexo confidencial"), "anexo.txt")})
    assert response.status_code == 302
    with web.connect_db() as db:
        row = db.execute("SELECT stored_path, restricted FROM documents WHERE original_name = 'anexo.txt'").fetchone()
    assert row is not None and row["restricted"] == 0
    raw = Path(row["stored_path"]).read_bytes()
    assert raw.startswith(vault.MAGIC) and b"confidencial" not in raw


def test_lawyer_cannot_upload_and_bad_formats_are_rejected(firm):
    web, ids = firm
    response = _client_as(web, ids["lawyer"]).post(
        f"/case/{ids['case']}/documents", content_type="multipart/form-data",
        data={"csrf_token": CSRF, "documents": (io.BytesIO(b"x"), "anexo.txt")})
    assert response.status_code == 403
    _client_as(web, ids["admin"]).post(
        f"/case/{ids['case']}/documents", content_type="multipart/form-data",
        data={"csrf_token": CSRF, "documents": (io.BytesIO(b"MZ"), "virus.exe")})
    with web.connect_db() as db:
        assert db.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1


def test_uploaded_restricted_document_is_hidden_from_assigned_lawyer(firm):
    web, ids = firm
    _client_as(web, ids["admin"]).post(
        f"/case/{ids['case']}/documents", content_type="multipart/form-data",
        data={"csrf_token": CSRF, "restricted": "1", "documents": (io.BytesIO(b"Reservado"), "reservado.txt")})
    page = _client_as(web, ids["lawyer"]).get(f"/case/{ids['case']}").get_data(as_text=True)
    assert "reservado.txt" not in page and "contrato.txt" in page
