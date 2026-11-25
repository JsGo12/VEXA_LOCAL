"""Citas clicables: cada fuente del chat abre el documento (en la página citada) en el visor de VEXA."""
import json

import pytest

from helpers import CSRF, _client_as, _web_app, add_case, add_document, add_user, admin_id
from vexa.rag import hybrid as rag_hybrid
from vexa.rag import model_select


@pytest.fixture
def web(monkeypatch, tmp_path):
    monkeypatch.setattr(model_select, "instalados_ollama", lambda: {"llama3.2:1b"})
    monkeypatch.setattr(model_select, "hardware", lambda: (8, 0))
    monkeypatch.setattr(rag_hybrid, "_embed", lambda *a, **k: None)
    monkeypatch.setattr(rag_hybrid, "reformular_pregunta", lambda q, h, m, host=None: q)
    monkeypatch.setattr(rag_hybrid, "consultar_stream", lambda *a, **k: iter(["La renta es 450000."]))
    web = _web_app(monkeypatch, tmp_path)
    a = admin_id(web)
    lawyer = add_user(web, "luis")
    case = add_case(web, a, user_id=lawyer, title="Arriendo")
    doc = add_document(web, case, a, "contrato.txt", b"La renta del arriendo es 450000 pesos mensuales.")
    return web, {"admin": a, "lawyer": lawyer, "case": case, "doc": doc, "other": add_user(web, "ajeno")}


def _done(response):
    events = [json.loads(line) for line in response.get_data(as_text=True).splitlines() if line.strip()]
    return next(e for e in events if e["type"] == "done")


def test_chat_sources_link_to_the_document_viewer(web):
    web, ids = web
    client = _client_as(web, ids["lawyer"])
    done = _done(client.post(f"/api/case/{ids['case']}/chat", json={"question": "renta"}, headers={"X-CSRF-Token": CSRF}))
    assert done["sources"] == ["contrato.txt — página 1"]
    assert done["links"] == [{"label": "contrato.txt — página 1", "url": f"/documents/{ids['doc']}/ver", "viewer": True}]
    history = client.get(f"/api/case/{ids['case']}/history").get_json()["messages"]
    assert history[-1]["links"][0]["url"] == f"/documents/{ids['doc']}/ver"


def test_pdf_links_jump_to_the_cited_page_and_other_formats_download(web):
    from vexa.routes.cases import source_links
    web, ids = web
    docs = [{"id": 7, "original_name": "demanda.pdf"}, {"id": 8, "original_name": "anexo.docx"},
            {"id": 9, "original_name": "copia.pdf"}, {"id": 10, "original_name": "copia.pdf"}]
    with web.app.test_request_context():
        from flask import g
        g.user = {"id": ids["admin"], "role": "admin"}
        links = source_links(["demanda.pdf — páginas 3-4", "anexo.docx — página 2", "copia.pdf — página 1",
                              "Ficha del expediente"], docs)
    assert links[0] == {"label": "demanda.pdf — páginas 3-4", "url": "/documents/7/ver#page=3", "viewer": True}
    assert links[1] == {"label": "anexo.docx — página 2", "url": "/documents/8", "viewer": False}
    assert links[2]["url"] is None            # dos documentos con el mismo nombre: no se adivina
    assert links[3]["url"] is None


def test_viewer_serves_inline_only_inside_vexa_and_is_audited(web):
    web, ids = web
    response = _client_as(web, ids["lawyer"]).get(f"/documents/{ids['doc']}/ver")
    assert response.status_code == 200 and response.mimetype == "text/plain"
    assert "attachment" not in response.headers.get("Content-Disposition", "")
    assert response.headers["Content-Security-Policy"] == "frame-ancestors 'self'"
    assert response.headers["X-Frame-Options"] == "SAMEORIGIN"
    assert response.get_data() == b"La renta del arriendo es 450000 pesos mensuales."
    with web.connect_db() as db:
        assert db.execute("SELECT COUNT(*) FROM audit_log WHERE action = 'documents.view' AND result = 'ok'").fetchone()[0] == 1


def test_viewer_respects_document_permissions(web):
    web, ids = web
    assert _client_as(web, ids["other"]).get(f"/documents/{ids['doc']}/ver").status_code in (403, 404)
    docx = add_document(web, ids["case"], ids["admin"], "anexo.docx", b"PK")
    response = _client_as(web, ids["lawyer"]).get(f"/documents/{docx}/ver")
    assert response.status_code == 302 and response.headers["Location"].endswith(f"/documents/{docx}")
