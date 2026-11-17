"""Abogados a cargo del abogado jefe, descarga del expediente en ZIP y vista del expediente con ventana emergente."""
import io
import zipfile

import pytest

from helpers import CSRF, _client_as, _web_app, add_case, add_document, add_user, admin_id, supervise


@pytest.fixture
def firm(monkeypatch, tmp_path):
    web = _web_app(monkeypatch, tmp_path)
    ids = {
        "admin": admin_id(web),
        "chief": add_user(web, "jefa", "chief_lawyer", "Abogada Jefa"),
        "mine": add_user(web, "luis"),          # quedará a cargo de la jefa
        "other": add_user(web, "otra"),         # no está a su cargo
    }
    ids["case_mine"] = add_case(web, ids["admin"], user_id=ids["mine"], title="Caso de Luis")
    ids["case_other"] = add_case(web, ids["admin"], user_id=ids["other"], title="Caso de Otra")
    add_document(web, ids["case_mine"], ids["admin"], "contrato.txt", b"Contrato de Luis.")
    add_document(web, ids["case_mine"], ids["admin"], "reservado.txt", b"Informe reservado.", restricted=1)
    return web, ids


def _post(client, path, **data):
    return client.post(path, data={"csrf_token": CSRF, **data})


def _supervised(web, chief_id):
    with web.connect_db() as db:
        return {r[0] for r in db.execute("SELECT lawyer_id FROM chief_lawyers WHERE chief_id = ?", (chief_id,))}


# ------------------------------------------------------------ abogados a cargo
def test_only_admin_assigns_lawyers_to_a_chief(firm):
    web, ids = firm
    chief = _client_as(web, ids["chief"])
    _post(chief, f"/admin/users/{ids['chief']}/lawyers", lawyer_ids=[ids["mine"], ids["other"]])
    assert _supervised(web, ids["chief"]) == set()
    admin = _client_as(web, ids["admin"])
    page = admin.get("/admin").get_data(as_text=True)
    assert "Abogados a cargo de cada abogado jefe" in page and "Abogada Jefa" in page
    _post(admin, f"/admin/users/{ids['chief']}/lawyers", lawyer_ids=[ids["mine"]])
    assert _supervised(web, ids["chief"]) == {ids["mine"]}
    # Solo se asignan abogados, y solo a cuentas de abogado jefe.
    _post(admin, f"/admin/users/{ids['chief']}/lawyers", lawyer_ids=[ids["admin"]])
    _post(admin, f"/admin/users/{ids['mine']}/lawyers", lawyer_ids=[ids["other"]])
    assert _supervised(web, ids["chief"]) == {ids["mine"]} and _supervised(web, ids["mine"]) == set()
    with web.connect_db() as db:
        results = [r[0] for r in db.execute("SELECT result FROM audit_log WHERE action = 'users.supervision_change'")]
    assert results.count("ok") == 1 and results.count("denied") == 3


def test_chief_sees_cases_of_supervised_lawyers_only(firm):
    web, ids = firm
    chief = _client_as(web, ids["chief"])
    assert chief.get(f"/case/{ids['case_mine']}").status_code == 403
    supervise(web, ids["chief"], ids["mine"])
    assert chief.get(f"/case/{ids['case_mine']}").status_code == 200
    assert chief.get(f"/case/{ids['case_other']}").status_code == 403
    panel = chief.get("/admin").get_data(as_text=True)
    assert "Caso de Luis" in panel and "Caso de Otra" not in panel
    assert "@luis" in panel and "@otra" not in panel          # solo administra a sus abogados
    follow = chief.get("/admin/seguimiento").get_data(as_text=True)
    assert "Caso de Luis" in follow and "Caso de Otra" not in follow


def test_chief_builds_teams_only_with_supervised_lawyers(firm):
    web, ids = firm
    supervise(web, ids["chief"], ids["mine"])
    chief = _client_as(web, ids["chief"])
    _post(chief, "/admin/teams", name="Mezclado", member_ids=[ids["mine"], ids["other"]])
    _post(chief, "/admin/teams", name="Mi equipo", member_ids=[ids["mine"]])
    with web.connect_db() as db:
        teams = {r["name"]: r["id"] for r in db.execute("SELECT id, name FROM teams")}
    assert set(teams) == {"Mi equipo"}
    # Un equipo armado por el administrador con abogados ajenos no lo puede editar.
    _post(_client_as(web, ids["admin"]), "/admin/teams", name="Ajeno", member_ids=[ids["other"]])
    with web.connect_db() as db:
        ajeno = db.execute("SELECT id FROM teams WHERE name = 'Ajeno'").fetchone()[0]
    _post(chief, f"/admin/teams/{ajeno}/members", member_ids=[ids["mine"]])
    with web.connect_db() as db:
        assert [r[0] for r in db.execute("SELECT user_id FROM team_members WHERE team_id = ?", (ajeno,))] == [ids["other"]]


def test_chief_assigns_cases_only_to_supervised_lawyers(firm):
    web, ids = firm
    supervise(web, ids["chief"], ids["mine"])
    chief = _client_as(web, ids["chief"])

    def create(title, assignee):
        return chief.post("/admin/cases", data={
            "csrf_token": CSRF, "title": title, "summary": "Resumen", "due_at": "2099-01-01T10:00",
            "assignment_type": "user", "assignee_id": str(assignee),
            "documents": (io.BytesIO(b"Texto del caso."), "caso.txt")}, content_type="multipart/form-data")

    create("Para Luis", ids["mine"])
    create("Para Otra", ids["other"])
    with web.connect_db() as db:
        titles = {r[0] for r in db.execute("SELECT title FROM cases")}
    assert "Para Luis" in titles and "Para Otra" not in titles
    # Tampoco reasigna casos fuera de su alcance ni hacia abogados ajenos.
    _post(chief, f"/admin/cases/{ids['case_other']}/assignment", assignment_type="user", assignee_id=str(ids["mine"]))
    _post(chief, f"/admin/cases/{ids['case_mine']}/assignment", assignment_type="user", assignee_id=str(ids["other"]))
    with web.connect_db() as db:
        owner = dict(db.execute("SELECT case_id, user_id FROM case_assignments").fetchall())
    assert owner[ids["case_other"]] == ids["other"] and owner[ids["case_mine"]] == ids["mine"]


def test_role_change_drops_supervision(firm):
    web, ids = firm
    supervise(web, ids["chief"], ids["mine"])
    _post(_client_as(web, ids["admin"]), f"/admin/users/{ids['chief']}/role", role="lawyer")
    assert _supervised(web, ids["chief"]) == set()


# --------------------------------------------------------------- expediente ZIP
def test_case_zip_contains_only_downloadable_documents(firm):
    web, ids = firm
    response = _client_as(web, ids["mine"]).get(f"/case/{ids['case_mine']}/expediente.zip")
    assert response.status_code == 200 and response.mimetype == "application/zip"
    with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
        assert archive.namelist() == ["contrato.txt"]                 # el restringido no se incluye
        assert archive.read("contrato.txt") == b"Contrato de Luis."    # descifrado
    admin_zip = _client_as(web, ids["admin"]).get(f"/case/{ids['case_mine']}/expediente.zip")
    with zipfile.ZipFile(io.BytesIO(admin_zip.data)) as archive:
        assert archive.namelist() == ["contrato.txt"]                 # restringido sin ACL: tampoco el admin
    assert _client_as(web, ids["other"]).get(f"/case/{ids['case_mine']}/expediente.zip").status_code == 403
    with web.connect_db() as db:
        db.execute("INSERT INTO user_permissions(user_id, permission, effect) VALUES (?, 'documents.download', 'deny')",
                   (ids["mine"],))
    assert _client_as(web, ids["mine"]).get(f"/case/{ids['case_mine']}/expediente.zip").status_code == 403
    with web.connect_db() as db:
        assert db.execute("SELECT COUNT(*) FROM audit_log WHERE action = 'cases.download' AND result = 'ok'").fetchone()[0] == 2


def test_case_view_has_compact_summary_dialog_and_wide_chat(firm):
    web, ids = firm
    page = _client_as(web, ids["mine"]).get(f"/case/{ids['case_mine']}").get_data(as_text=True)
    assert 'class="summary-card"' in page and 'data-open-dialog="caseDialog"' in page
    assert '<dialog id="caseDialog"' in page and "Descargar expediente (ZIP)" in page
    assert "assistant-panel-wide" in page and "js/case-dialog.js" in page
    # Los documentos están dentro de la ventana emergente, no al lado del chat.
    dialog_at = page.index('<dialog id="caseDialog"')
    assert page.index('class="document-list"') > dialog_at and page.index("expediente.zip") > dialog_at
    assert "documents-panel" not in page
