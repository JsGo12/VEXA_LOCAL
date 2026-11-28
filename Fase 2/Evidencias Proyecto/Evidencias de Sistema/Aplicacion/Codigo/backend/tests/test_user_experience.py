"""Experiencia de uso: tema, vista de casos con filtros, exportación a Excel y subida con progreso."""
import io

import pytest
from openpyxl import load_workbook

from helpers import CSRF, _client_as, _web_app, add_case, add_user, admin_id, supervise


@pytest.fixture
def firm(monkeypatch, tmp_path):
    web = _web_app(monkeypatch, tmp_path)
    ids = {"admin": admin_id(web), "chief": add_user(web, "jefa", "chief_lawyer", "Carla Jefa"),
           "lawyer": add_user(web, "luis", name="Luis Soto"), "other": add_user(web, "otra", name="Otra")}
    supervise(web, ids["chief"], ids["lawyer"])
    ids["case"] = add_case(web, ids["admin"], user_id=ids["lawyer"], title="Despido injustificado")
    ids["secret"] = add_case(web, ids["admin"], user_id=ids["other"], title="Fusión confidencial")
    return web, ids


def test_theme_toggle_and_light_stylesheet_are_present(firm):
    web, ids = firm
    page = _client_as(web, ids["lawyer"]).get("/lawyer").get_data(as_text=True)
    assert 'data-theme="dark"' in page and "data-theme-toggle" in page
    assert "css/theme-light.css" in page and "js/theme.js" in page
    assert "<script>" not in page                                   # sin scripts en línea (CSP)


def test_case_lists_offer_filters_sorting_and_table_view(firm):
    web, ids = firm
    for user, path in ((ids["lawyer"], "/lawyer"), (ids["admin"], "/admin")):
        page = _client_as(web, user).get(path).get_data(as_text=True)
        assert 'data-collection=' in page and 'data-filter="status"' in page and 'data-filter="deadline"' in page
        assert 'data-sort' in page and 'data-view="table"' in page and 'data-view-panel="table"' in page
        assert 'data-deadline="al_dia"' in page and "js/case-collection.js" in page
    admin_page = _client_as(web, ids["admin"]).get("/admin").get_data(as_text=True)
    # Las ventanas de reasignar están fuera de las tarjetas (abren también desde la tabla).
    assert admin_page.index('<dialog id="reassign-') > admin_page.index('data-view-panel="table"')


def test_follow_up_export_respects_scope(firm):
    web, ids = firm
    response = _client_as(web, ids["admin"]).get("/admin/seguimiento/exportar.xlsx")
    assert response.status_code == 200 and response.mimetype.endswith("spreadsheetml.sheet")
    sheet = load_workbook(io.BytesIO(response.data))["Seguimiento"]
    titles = [row[0].value for row in sheet.iter_rows(min_row=2)]
    assert set(titles) == {"Despido injustificado", "Fusión confidencial"}
    chief = load_workbook(io.BytesIO(_client_as(web, ids["chief"]).get("/admin/seguimiento/exportar.xlsx").data))
    assert [row[0].value for row in chief["Seguimiento"].iter_rows(min_row=2)] == ["Despido injustificado"]
    assert _client_as(web, ids["lawyer"]).get("/admin/seguimiento/exportar.xlsx").status_code == 403


def test_audit_export_uses_plain_language_and_filters(firm):
    web, ids = firm
    admin = _client_as(web, ids["admin"])
    admin.get(f"/case/{ids['case']}")
    _client_as(web, ids["other"]).get(f"/case/{ids['case']}")      # acceso denegado
    data = admin.get("/admin/audit/exportar.xlsx?result=denied").data
    rows = list(load_workbook(io.BytesIO(data))["Auditoría"].iter_rows(min_row=2, values_only=True))
    assert rows and all(r[5] == "Denegado" for r in rows)
    assert any("sin autorización" in r[4] for r in rows)
    with web.connect_db() as db:
        assert db.execute("SELECT COUNT(*) FROM audit_log WHERE action = 'exports.audit'").fetchone()[0] == 1


def test_progress_upload_gets_json_redirect_and_keeps_flash(firm):
    web, ids = firm
    admin = _client_as(web, ids["admin"])
    response = admin.post(f"/case/{ids['case']}/documents", headers={"X-Requested-With": "vexa-upload"},
                          data={"csrf_token": CSRF, "next": "admin", "documents": (io.BytesIO(b"x"), "anexo.txt")},
                          content_type="multipart/form-data")
    assert response.get_json() == {"ok": True, "redirect": "/admin"}
    assert "1 documento(s) agregado(s)" in admin.get("/admin").get_data(as_text=True)   # el mensaje no se pierde
    bad = admin.post(f"/case/{ids['case']}/documents", headers={"X-Requested-With": "vexa-upload"},
                     data={"csrf_token": CSRF, "documents": (io.BytesIO(b"x"), "virus.exe")},
                     content_type="multipart/form-data")
    assert bad.get_json()["redirect"].endswith(f"/case/{ids['case']}")
    page = _client_as(web, ids["admin"]).get(f"/case/{ids['case']}").get_data(as_text=True)
    assert "js/upload.js" in page


def test_tables_have_mobile_labels(firm):
    web, ids = firm
    page = _client_as(web, ids["admin"]).get("/admin/seguimiento").get_data(as_text=True)
    assert 'class="data-table responsive-table"' in page and 'data-label="Fecha límite"' in page
