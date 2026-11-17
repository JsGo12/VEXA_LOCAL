"""Auditoría en lenguaje claro: etiquetas, frases, hora local y sin filtrar títulos fuera del alcance."""
import re
from pathlib import Path

import pytest

from helpers import CSRF, _client_as, _web_app, add_case, add_document, add_user, admin_id, supervise
from vexa.services import audit_view

BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture
def firm(monkeypatch, tmp_path):
    web = _web_app(monkeypatch, tmp_path)
    ids = {"admin": admin_id(web), "chief": add_user(web, "jefa", "chief_lawyer", "Carla Jefa"),
           "lawyer": add_user(web, "luis", name="Luis Soto"), "other": add_user(web, "otra", name="Otra Abogada")}
    ids["case"] = add_case(web, ids["admin"], user_id=ids["lawyer"], title="Despido injustificado")
    ids["secret_case"] = add_case(web, ids["admin"], user_id=ids["other"], title="Fusión confidencial")
    ids["doc"] = add_document(web, ids["case"], ids["admin"], "contrato.txt", b"Contrato.")
    return web, ids


def test_every_audited_action_has_a_readable_label():
    """Si alguien agrega un audit.record nuevo sin etiqueta, esta prueba lo avisa."""
    source = "\n".join(p.read_text(encoding="utf-8") for p in (BACKEND / "vexa").rglob("*.py"))
    actions = set(re.findall(r'audit\.record\(\s*"([a-z_.]+)"', source))
    for pair in re.findall(r'audit\.record\(\s*"([a-z_.]+)" if [^"]+ else "([a-z_.]+)"', source):
        actions |= set(pair)                                     # "users.activate" if ... else "users.deactivate"
    actions.add("access.denied")
    assert {"auth.login", "cases.open", "users.deactivate"} <= actions
    missing = sorted(a for a in actions if a not in audit_view.ACTION_LABELS)
    assert not missing, f"Acciones sin etiqueta legible: {missing}"


def test_audit_page_shows_plain_language_not_codes(firm):
    web, ids = firm
    admin = _client_as(web, ids["admin"])
    admin.get(f"/case/{ids['case']}")
    admin.post(f"/case/{ids['case']}/progress", data={"csrf_token": CSRF, "status": "en_revision", "progress": "60",
                                                       "note": "texto privado"})
    admin.post(f"/admin/cases/{ids['case']}/due", data={"csrf_token": CSRF, "due_at": "2099-03-01T09:30"})
    _client_as(web, ids["other"]).get(f"/case/{ids['case']}")          # acceso denegado
    text = admin.get("/admin/audit").get_data(as_text=True)
    table = text[text.index("<tbody>"):text.index("</tbody>")]
    assert "<code>" not in table and "cases.open" not in table and '{"' not in table
    assert "Abrió el expediente «Despido injustificado»." in table
    assert "Actualizó el avance de «Despido injustificado»: En revisión, 60 % y dejó una nota." in table
    assert "Cambió la fecha límite de «Despido injustificado» del 01-01-2099 00:00 al 01-03-2099 09:30." in table
    assert "Intentó «abrir expedientes dentro de su alcance» sobre «Despido injustificado» sin autorización." in table
    assert "Motivo: expediente fuera de su alcance" in table
    assert "texto privado" not in text                               # las notas nunca llegan a la auditoría
    assert "Expediente abierto" in text and "Este equipo" in table   # filtro y origen legibles


def test_chief_auditor_does_not_see_titles_outside_scope(firm):
    web, ids = firm
    _client_as(web, ids["admin"]).get(f"/case/{ids['secret_case']}")
    supervise(web, ids["chief"], ids["lawyer"])
    text = _client_as(web, ids["chief"]).get("/admin/audit").get_data(as_text=True)
    assert "Fusión confidencial" not in text and f"el caso #{ids['secret_case']}" in text


def test_local_time_and_unknown_actions_are_safe():
    assert audit_view.local_time("") == ""
    assert re.fullmatch(r"\d{2}-\d{2}-\d{4} \d{2}:\d{2}:\d{2}", audit_view.local_time("2026-11-14T01:15:51.123Z"))
    assert audit_view.action_label("algo.nuevo_evento") == "Algo · nuevo evento"
