"""Vista de Permisos: por persona (grupos y botones) y por documento (quién lo ve y por qué)."""
import pytest

from helpers import CSRF, _client_as, _web_app, add_case, add_document, add_user, admin_id, supervise


@pytest.fixture
def firm(monkeypatch, tmp_path):
    web = _web_app(monkeypatch, tmp_path)
    ids = {"admin": admin_id(web), "chief": add_user(web, "jefa", "chief_lawyer", "Carla Jefa"),
           "lawyer": add_user(web, "luis", name="Luis Soto"), "other": add_user(web, "otra", name="Otra Abogada")}
    ids["case"] = add_case(web, ids["admin"], user_id=ids["lawyer"], title="Despido injustificado")
    ids["secret_case"] = add_case(web, ids["admin"], user_id=ids["other"], title="Fusión confidencial")
    ids["doc"] = add_document(web, ids["case"], ids["admin"], "contrato.txt", b"Contrato.")
    ids["reserved"] = add_document(web, ids["case"], ids["admin"], "reservado.txt", b"Reservado.", restricted=1)
    return web, ids


def test_person_view_groups_permissions_with_segmented_buttons(firm):
    web, ids = firm
    admin = _client_as(web, ids["admin"])
    text = admin.get(f"/admin/permissions?mode=personas&user_id={ids['lawyer']}").get_data(as_text=True)
    assert "Casos" in text and "Asistente IA" in text and "Incluido en el rol" in text
    assert 'name="effect" value="allow"' in text and 'name="effect" value="clear"' in text
    assert "<code>cases.view</code>" not in text                       # sin códigos a la vista
    # El botón «Conceder» de una fila aplica el ajuste directamente.
    response = admin.post(f"/admin/permissions/users/{ids['lawyer']}/override",
                          data={"csrf_token": CSRF, "permission": "documents.upload", "effect": "allow"})
    assert response.headers["Location"].endswith(f"mode=personas&user_id={ids['lawyer']}")
    text = admin.get(f"/admin/permissions?user_id={ids['lawyer']}").get_data(as_text=True)
    assert "Concedido manualmente" in text and "is-active is-allow" in text


def test_document_view_explains_who_can_see_each_document(firm):
    web, ids = firm
    with web.connect_db() as db:
        db.execute("INSERT INTO document_acl(document_id, user_id, effect) VALUES (?, ?, 'deny')", (ids["doc"], ids["other"]))
        db.execute("INSERT INTO access_grants(user_id, scope_type, scope_id) VALUES (?, 'case', ?)", (ids["other"], ids["case"]))
    _client_as(web, ids["lawyer"]).get(f"/documents/{ids['doc']}")          # una descarga registrada
    text = _client_as(web, ids["admin"]).get(f"/admin/permissions?mode=documentos&case_id={ids['case']}").get_data(as_text=True)
    assert "Quién puede verlo" in text and "Caso asignado a su cuenta" in text
    assert "Bloqueado por una regla de este documento" in text            # Otra: regla denegar
    assert "Documento restringido y sin excepción" in text                # reservado.txt
    assert "Subido por" in text and "(cifrado)" in text and "huella" in text
    assert "Últimas descargas" in text and "@luis" in text


def test_chief_sees_only_cases_and_people_in_scope(firm):
    web, ids = firm
    supervise(web, ids["chief"], ids["lawyer"])
    chief = _client_as(web, ids["chief"])
    text = chief.get("/admin/permissions?mode=documentos").get_data(as_text=True)
    assert "Despido injustificado" in text and "Fusión confidencial" not in text
    text = chief.get("/admin/permissions?mode=personas").get_data(as_text=True)
    assert "Luis Soto" in text and "Otra Abogada" not in text
    # Pedir por URL a alguien que no está a su cargo no muestra su política.
    text = chief.get(f"/admin/permissions?user_id={ids['other']}").get_data(as_text=True)
    assert "Otra Abogada" not in text and "Elige una persona" in text
    text = chief.get(f"/admin/permissions?mode=documentos&case_id={ids['secret_case']}").get_data(as_text=True)
    assert "Fusión confidencial" not in text and "Caso fuera de tu alcance" in text
