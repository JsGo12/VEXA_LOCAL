"""Perfil abogado jefe, permisos granulares, precedencia documental y prevención de escalada."""
import pytest

from helpers import CSRF, _client_as, _web_app, add_case, add_document, add_user, admin_id, grant
from vexa.permissions import policy
from vexa.permissions.catalog import ROLE_PERMISSIONS


@pytest.fixture
def firm(monkeypatch, tmp_path):
    web = _web_app(monkeypatch, tmp_path)
    ids = {
        "admin": admin_id(web),
        "chief": add_user(web, "jefa", "chief_lawyer", "Abogada Jefa"),
        "lawyer": add_user(web, "luis"),
        "other": add_user(web, "otra"),
    }
    ids["case"] = add_case(web, ids["admin"], user_id=ids["lawyer"], title="Arriendo Pérez")
    ids["doc"] = add_document(web, ids["case"], ids["admin"], "contrato.txt", b"Contrato de arriendo.")
    ids["secret"] = add_document(web, ids["case"], ids["admin"], "reservado.txt", b"Informe reservado.", restricted=1)
    return web, ids


def _user(web, user_id):
    with web.connect_db() as db:
        return db.execute("SELECT id, name, username, role FROM users WHERE id = ?", (user_id,)).fetchone()


def test_initial_policy_matrix_is_explicit():
    assert ROLE_PERMISSIONS["lawyer"] == {"cases.view", "documents.view", "documents.download", "cases.update_progress"}
    assert "documents.upload" not in ROLE_PERMISSIONS["lawyer"]
    assert "assistant.use" in ROLE_PERMISSIONS["chief_lawyer"]
    assert "assistant.use" not in ROLE_PERMISSIONS["lawyer"]
    # El administrador tiene todos los permisos del catálogo, incluido el asistente.
    from vexa.permissions.catalog import PERMISSIONS
    assert ROLE_PERMISSIONS["admin"] == set(PERMISSIONS)
    assert {"assistant.use", "assistant.firm_access"} <= ROLE_PERMISSIONS["admin"]


def test_role_alone_never_grants_document_access(firm):
    web, ids = firm
    client = _client_as(web, ids["chief"])
    assert client.get(f"/case/{ids['case']}").status_code == 403
    assert client.get(f"/documents/{ids['doc']}").status_code == 403
    with web.connect_db() as db:
        assert policy.case_scope(db, _user(web, ids["chief"])) == {}


def test_chief_with_explicit_firm_scope_can_open_cases_but_not_restricted_documents(firm):
    web, ids = firm
    grant(web, ids["chief"], "firm")
    client = _client_as(web, ids["chief"])
    assert client.get(f"/case/{ids['case']}").status_code == 200
    assert client.get(f"/documents/{ids['doc']}").status_code == 200
    assert client.get(f"/documents/{ids['secret']}").status_code == 403   # la restricción prevalece


def test_document_allow_exception_and_deny_precedence(firm):
    web, ids = firm
    with web.connect_db() as db:
        db.execute("INSERT INTO document_acl(document_id, user_id, effect) VALUES (?, ?, 'allow')",
                   (ids["secret"], ids["lawyer"]))
        db.execute("INSERT INTO document_acl(document_id, user_id, effect) VALUES (?, ?, 'deny')",
                   (ids["doc"], ids["lawyer"]))
    client = _client_as(web, ids["lawyer"])
    assert client.get(f"/documents/{ids['secret']}").status_code == 200    # excepción explícita
    assert client.get(f"/documents/{ids['doc']}").status_code == 403       # deny gana sobre la asignación
    with web.connect_db() as db:
        visible = [d["original_name"] for d in policy.visible_documents(db, _user(web, ids["lawyer"]), ids["case"])]
    assert visible == ["reservado.txt"]


def test_permission_override_deny_wins_over_role(firm):
    web, ids = firm
    with web.connect_db() as db:
        db.execute("INSERT INTO user_permissions(user_id, permission, effect) VALUES (?, 'documents.download', 'deny')",
                   (ids["lawyer"],))
    client = _client_as(web, ids["lawyer"])
    assert client.get(f"/case/{ids['case']}").status_code == 200
    assert client.get(f"/documents/{ids['doc']}").status_code == 403


def test_revoking_scope_takes_effect_on_the_next_request(firm):
    web, ids = firm
    grant(web, ids["chief"], "case", ids["case"])
    client = _client_as(web, ids["chief"])
    assert client.get(f"/case/{ids['case']}").status_code == 200
    with web.connect_db() as db:
        db.execute("DELETE FROM access_grants WHERE user_id = ?", (ids["chief"],))
    assert client.get(f"/case/{ids['case']}").status_code == 403


def test_team_assignment_and_team_grant(firm):
    web, ids = firm
    with web.connect_db() as db:
        team = db.execute("INSERT INTO teams(name) VALUES ('Civil')").lastrowid
        db.execute("INSERT INTO team_members(team_id, user_id) VALUES (?, ?)", (team, ids["other"]))
        db.execute("UPDATE case_assignments SET user_id = NULL, team_id = ? WHERE case_id = ?", (team, ids["case"]))
    assert _client_as(web, ids["other"]).get(f"/case/{ids['case']}").status_code == 200
    assert _client_as(web, ids["lawyer"]).get(f"/case/{ids['case']}").status_code == 403
    grant(web, ids["chief"], "team", team)
    with web.connect_db() as db:
        assert policy.case_paths(db, _user(web, ids["chief"]), ids["case"]) == {"grant_team"}


def test_user_cannot_elevate_own_permissions_or_role(firm):
    web, ids = firm
    client = _client_as(web, ids["chief"])
    client.post(f"/admin/permissions/users/{ids['chief']}/grants",
                data={"scope_type": "firm", "csrf_token": CSRF})
    client.post(f"/admin/users/{ids['chief']}/role", data={"role": "admin", "csrf_token": CSRF})
    with web.connect_db() as db:
        assert db.execute("SELECT COUNT(*) FROM access_grants WHERE user_id = ?", (ids["chief"],)).fetchone()[0] == 0
        assert db.execute("SELECT role FROM users WHERE id = ?", (ids["chief"],)).fetchone()[0] == "chief_lawyer"
        denied = db.execute("SELECT COUNT(*) FROM audit_log WHERE result = 'denied' AND user_id = ?",
                            (ids["chief"],)).fetchone()[0]
    assert denied >= 2


def test_chief_can_only_grant_what_they_hold(firm):
    web, ids = firm
    client = _client_as(web, ids["chief"])
    client.post(f"/admin/permissions/users/{ids['other']}/grants", data={"scope_type": "firm", "csrf_token": CSRF})
    client.post(f"/admin/permissions/users/{ids['other']}/grants",
                data={"scope_type": "case", "scope_id": f"case:{ids['case']}", "csrf_token": CSRF})
    with web.connect_db() as db:
        assert db.execute("SELECT COUNT(*) FROM access_grants WHERE user_id = ?", (ids["other"],)).fetchone()[0] == 0
    grant(web, ids["chief"], "case", ids["case"])
    client.post(f"/admin/permissions/users/{ids['other']}/grants",
                data={"scope_type": "case", "scope_id": f"case:{ids['case']}", "csrf_token": CSRF})
    with web.connect_db() as db:
        assert db.execute("SELECT scope_type, scope_id FROM access_grants WHERE user_id = ?",
                          (ids["other"],)).fetchone()[:] == ("case", ids["case"])


def test_chief_cannot_manage_admins_or_create_privileged_accounts(firm):
    web, ids = firm
    client = _client_as(web, ids["chief"])
    client.post(f"/admin/users/{ids['admin']}/active", data={"active": "0", "csrf_token": CSRF})
    client.post("/admin/users", data={"name": "X", "username": "nuevoadmin", "password": "ContrasenaLarga1",
                                      "role": "admin", "csrf_token": CSRF})
    client.post(f"/admin/permissions/users/{ids['admin']}/override",
                data={"permission": "audit.view", "effect": "deny", "csrf_token": CSRF})
    with web.connect_db() as db:
        assert db.execute("SELECT active FROM users WHERE id = ?", (ids["admin"],)).fetchone()[0] == 1
        assert db.execute("SELECT 1 FROM users WHERE username = 'nuevoadmin'").fetchone() is None
        assert db.execute("SELECT COUNT(*) FROM user_permissions WHERE user_id = ?", (ids["admin"],)).fetchone()[0] == 0


def test_chief_can_manage_lawyers(firm):
    web, ids = firm
    client = _client_as(web, ids["chief"])
    assert client.get("/admin").status_code == 200
    client.post("/admin/users", data={"name": "Nueva", "username": "nueva", "password": "ContrasenaLarga1",
                                      "role": "lawyer", "csrf_token": CSRF})
    client.post(f"/admin/users/{ids['other']}/active", data={"active": "0", "csrf_token": CSRF})
    with web.connect_db() as db:
        assert db.execute("SELECT role FROM users WHERE username = 'nueva'").fetchone()[0] == "lawyer"
        assert db.execute("SELECT active FROM users WHERE id = ?", (ids["other"],)).fetchone()[0] == 0


def test_lawyer_cannot_reach_permission_or_audit_management(firm):
    web, ids = firm
    client = _client_as(web, ids["lawyer"])
    assert client.get("/admin/permissions").status_code == 403
    assert client.get("/admin/audit").status_code == 403
    response = client.post(f"/admin/permissions/users/{ids['lawyer']}/override",
                           data={"permission": "assistant.use", "effect": "allow", "csrf_token": CSRF})
    assert response.status_code == 403
    response = client.post(f"/admin/permissions/documents/{ids['secret']}/acl",
                           data={"user_id": ids["lawyer"], "effect": "allow", "csrf_token": CSRF})
    assert response.status_code == 403
    with web.connect_db() as db:
        assert db.execute("SELECT COUNT(*) FROM user_permissions").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM document_acl").fetchone()[0] == 0


def test_deactivated_user_session_is_dropped(firm):
    web, ids = firm
    client = _client_as(web, ids["lawyer"])
    assert client.get(f"/case/{ids['case']}").status_code == 200
    with web.connect_db() as db:
        db.execute("UPDATE users SET active = 0 WHERE id = ?", (ids["lawyer"],))
    assert client.get(f"/case/{ids['case']}").status_code == 302


def test_admin_keeps_legacy_firm_access_through_explicit_grant(firm):
    web, ids = firm
    client = _client_as(web, ids["admin"])
    assert client.get(f"/case/{ids['case']}").status_code == 200
    with web.connect_db() as db:
        db.execute("DELETE FROM access_grants WHERE user_id = ?", (ids["admin"],))
    assert client.get(f"/case/{ids['case']}").status_code == 403   # revocable: no depende del nombre del rol


def test_management_pages_render_for_privileged_roles(firm):
    web, ids = firm
    grant(web, ids["chief"], "firm")
    chief = _client_as(web, ids["chief"])
    for path in ("/chief", "/admin", "/admin/permissions", f"/admin/permissions?user_id={ids['lawyer']}&case_id={ids['case']}",
                 "/admin/audit", "/assistant", "/lawyer"):
        assert chief.get(path).status_code == 200, path
    admin = _client_as(web, ids["admin"])
    assert admin.get("/").headers["Location"].endswith("/admin")
    assert chief.get("/").headers["Location"].endswith("/chief")
    assert _client_as(web, ids["lawyer"]).get("/").headers["Location"].endswith("/lawyer")
