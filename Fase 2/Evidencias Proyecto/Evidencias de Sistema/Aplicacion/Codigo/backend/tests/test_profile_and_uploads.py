"""Mi perfil, botones de Seguimiento y carga de documentos a casos ya creados por jefe y administrador."""
import io

import pytest

from helpers import CSRF, PASSWORD, _client_as, _web_app, add_case, add_document, add_user, admin_id, supervise


@pytest.fixture
def firm(monkeypatch, tmp_path):
    web = _web_app(monkeypatch, tmp_path)
    ids = {"admin": admin_id(web), "chief": add_user(web, "jefa", "chief_lawyer", "Abogada Jefa"),
           "lawyer": add_user(web, "luis", name="Luis Soto"), "other": add_user(web, "otra")}
    ids["case"] = add_case(web, ids["admin"], user_id=ids["lawyer"], title="Arriendo")
    ids["case_other"] = add_case(web, ids["admin"], user_id=ids["other"], title="Ajeno")
    add_document(web, ids["case"], ids["admin"], "contrato.txt", b"Contrato.")
    return web, ids


def _upload(client, case_id, **extra):
    return client.post(f"/case/{case_id}/documents", data={
        "csrf_token": CSRF, "documents": (io.BytesIO(b"Anexo nuevo."), "anexo.txt"), **extra},
        content_type="multipart/form-data")


def _doc_count(web, case_id):
    with web.connect_db() as db:
        return db.execute("SELECT COUNT(*) FROM documents WHERE case_id = ?", (case_id,)).fetchone()[0]


# ------------------------------------------------------------------- perfil
def test_profile_shows_account_cases_and_permissions(firm):
    web, ids = firm
    client = _client_as(web, ids["lawyer"])
    page = client.get("/account")
    assert page.status_code == 200
    text = page.get_data(as_text=True)
    assert "Luis Soto" in text and "@luis" in text and "Arriendo" in text and "Ajeno" not in text
    assert "Registrar notas y evidencias" in text               # permisos efectivos en lenguaje claro
    assert "Cambiar el estado y el porcentaje" not in text
    assert 'href="/account"' in text                            # la barra superior lleva al perfil
    supervise(web, ids["chief"], ids["lawyer"])
    assert "Abogada Jefa" in client.get("/account").get_data(as_text=True)          # su jefe
    assert "Luis Soto" in _client_as(web, ids["chief"]).get("/account").get_data(as_text=True)  # a su cargo


def test_profile_updates_own_name_only(firm):
    web, ids = firm
    client = _client_as(web, ids["lawyer"])
    client.post("/account", data={"csrf_token": CSRF, "name": "  Luis   Andrés Soto ", "username": "hacker",
                                  "role": "admin"})
    client.post("/account", data={"csrf_token": CSRF, "name": "   "})
    with web.connect_db() as db:
        row = db.execute("SELECT name, username, role FROM users WHERE id = ?", (ids["lawyer"],)).fetchone()
    assert tuple(row) == ("Luis Andrés Soto", "luis", "lawyer")


def test_password_change_from_profile_returns_to_profile(firm):
    web, ids = firm
    client = _client_as(web, ids["lawyer"])
    bad = client.post("/account/password", data={"csrf_token": CSRF, "next": "profile", "current_password": "mala",
                                                 "new_password": "OtraClave-123", "confirm_password": "OtraClave-123"})
    assert bad.status_code == 302 and bad.headers["Location"].endswith("/account#seguridad")
    with client.session_transaction() as s:
        token = s["csrf_token"]
    ok = client.post("/account/password", data={"csrf_token": token, "next": "profile", "current_password": PASSWORD,
                                                "new_password": "OtraClave-123", "confirm_password": "OtraClave-123"})
    assert ok.status_code == 302 and ok.headers["Location"].endswith("/account")


# ---------------------------------------------------------------- seguimiento
def test_follow_up_uses_action_buttons_and_dialogs(firm):
    web, ids = firm
    text = _client_as(web, ids["admin"]).get("/admin/seguimiento").get_data(as_text=True)
    assert f'data-open-dialog="due-{ids["case"]}"' in text and f'<dialog id="due-{ids["case"]}"' in text
    assert f'data-open-dialog="upload-{ids["case"]}"' in text and "js/case-dialog.js" in text
    table = text[text.index('<table class="data-table'):text.index("</table>")]
    assert "button button-quiet" not in table and 'class="row-actions"' in table   # sin los botones antiguos
    supervise(web, ids["chief"], ids["lawyer"])
    chief_text = _client_as(web, ids["chief"]).get("/admin/seguimiento").get_data(as_text=True)
    assert 'id="due-' not in chief_text and f'data-open-dialog="upload-{ids["case"]}"' in chief_text


# ------------------------------------------------- documentos en casos existentes
def test_admin_and_chief_add_documents_to_existing_cases(firm):
    web, ids = firm
    admin = _client_as(web, ids["admin"])
    page = admin.get(f"/case/{ids['case']}").get_data(as_text=True)
    assert 'data-open-dialog="uploadDialog"' in page and '<dialog id="uploadDialog"' in page
    assert _upload(admin, ids["case"]).headers["Location"].endswith(f"/case/{ids['case']}")
    assert _upload(admin, ids["case"], next="admin").headers["Location"].endswith("/admin")
    assert _upload(admin, ids["case"], next="seguimiento").headers["Location"].endswith("/admin/seguimiento")
    assert _upload(admin, ids["case"], next="https://evil.example").headers["Location"].endswith(f"/case/{ids['case']}")
    assert _doc_count(web, ids["case"]) == 5
    assert 'data-open-dialog="upload-' in admin.get("/admin").get_data(as_text=True)

    chief = _client_as(web, ids["chief"])
    assert _upload(chief, ids["case"]).status_code == 403        # aún no está a su cargo
    supervise(web, ids["chief"], ids["lawyer"])
    assert _upload(chief, ids["case"], next="admin").status_code == 302
    assert _upload(chief, ids["case_other"]).status_code == 403  # caso de un abogado ajeno
    assert _doc_count(web, ids["case"]) == 6 and _doc_count(web, ids["case_other"]) == 0

    lawyer = _client_as(web, ids["lawyer"])
    assert 'id="uploadDialog"' not in lawyer.get(f"/case/{ids['case']}").get_data(as_text=True)
    assert _upload(lawyer, ids["case"]).status_code == 403


# ------------------------------------------------------------ administración por pestañas
def test_admin_panel_is_organized_in_tabs(firm):
    web, ids = firm
    admin = _client_as(web, ids["admin"])
    page = admin.get("/admin").get_data(as_text=True)
    for tab in ("casos", "usuarios", "equipos", "supervision"):
        assert f'data-tab="{tab}"' in page and f'id="tab-{tab}"' in page
    assert 'id="tab-casos" role="tabpanel" hidden' not in page             # casos visible por defecto
    assert 'id="tab-usuarios" role="tabpanel" hidden' in page
    # Los formularios ya no están abiertos: se abren en ventanas.
    assert 'data-open-dialog="newCase"' in page and '<dialog id="newCase"' in page
    assert f'data-open-dialog="user-{ids["lawyer"]}"' in page and 'data-open-dialog="newUser"' in page
    users_tab = admin.get("/admin?tab=usuarios").get_data(as_text=True)
    assert 'id="tab-usuarios" role="tabpanel" hidden' not in users_tab and 'id="tab-casos" role="tabpanel" hidden' in users_tab
    # Tras guardar, vuelve a la pestaña donde se hizo la acción.
    response = admin.post(f"/admin/users/{ids['other']}/active", data={"csrf_token": CSRF, "active": "0"})
    assert response.headers["Location"].endswith("/admin?tab=usuarios")
    response = admin.post("/admin/teams", data={"csrf_token": CSRF, "name": "Civil", "member_ids": [ids["lawyer"]]})
    assert response.headers["Location"].endswith("/admin?tab=equipos")
    # El jefe no ve la pestaña de supervisión.
    supervise(web, ids["chief"], ids["lawyer"])
    chief_page = _client_as(web, ids["chief"]).get("/admin?tab=supervision").get_data(as_text=True)
    assert 'data-tab="supervision"' not in chief_page and 'id="tab-casos" role="tabpanel" hidden' not in chief_page
