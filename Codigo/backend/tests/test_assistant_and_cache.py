"""Asistente transversal y cachés: solo material autorizado, sin fugas entre usuarios."""
import json

import pytest

from helpers import CSRF, _client_as, _web_app, add_case, add_document, add_user, admin_id, grant
from vexa.rag import hybrid as rag_hybrid
from vexa.rag import model_select
from vexa.routes import cases as case_routes


@pytest.fixture
def fake_ollama(monkeypatch):
    """Ollama simulado: registra los fragmentos que llegarían al modelo."""
    seen = []
    monkeypatch.setattr(model_select, "instalados_ollama", lambda: {"llama3.2:1b"})
    monkeypatch.setattr(model_select, "hardware", lambda: (8, 0))
    monkeypatch.setattr(rag_hybrid, "_embed", lambda *a, **k: None)
    monkeypatch.setattr(rag_hybrid, "reformular_pregunta", lambda q, h, m, host=None: q)

    def fake_stream(question, fragments, history, modelo, host=None, opciones=None, sistema=None):
        seen.append({"docs": sorted({f.doc_name for f in fragments}), "system": sistema})
        yield "respuesta simulada"

    monkeypatch.setattr(rag_hybrid, "consultar_stream", fake_stream)
    return seen


@pytest.fixture
def firm(monkeypatch, tmp_path):
    web = _web_app(monkeypatch, tmp_path)
    a = admin_id(web)
    ids = {"admin": a, "chief": add_user(web, "jefa", "chief_lawyer"), "chief2": add_user(web, "jefe2", "chief_lawyer"),
           "lawyer": add_user(web, "luis")}
    ids["case1"] = add_case(web, a, user_id=ids["lawyer"], title="Arriendo Pérez")
    ids["case2"] = add_case(web, a, user_id=ids["lawyer"], title="Despido Soto")
    ids["d1"] = add_document(web, ids["case1"], a, "contrato.txt", b"La renta del arriendo de Juan Perez es 450000 pesos.")
    ids["d2"] = add_document(web, ids["case2"], a, "carta.txt", b"Juan Perez figura como testigo del despido de Soto.")
    ids["sec"] = add_document(web, ids["case1"], a, "reservado.txt", b"Juan Perez tiene una deuda reservada.", restricted=1)
    return web, ids


def _ask(client, question, case_ids=None):
    conv = client.post("/api/assistant/conversations", json={"title": question}, headers={"X-CSRF-Token": CSRF})
    if conv.status_code != 200:
        return conv, None
    cid = conv.get_json()["id"]
    body = {"question": question}
    if case_ids is not None:
        body["case_ids"] = case_ids
    response = client.post(f"/api/assistant/conversations/{cid}/ask", json=body, headers={"X-CSRF-Token": CSRF})
    response.get_data()   # consume el streaming NDJSON para ejecutar la generación completa
    return response, cid


def _events(response):
    return [json.loads(line) for line in response.get_data(as_text=True).splitlines() if line.strip()]


def test_lawyer_cannot_use_firm_assistant(firm, fake_ollama):
    web, ids = firm
    client = _client_as(web, ids["lawyer"])
    assert client.get("/assistant").status_code == 403
    assert client.get("/api/assistant/conversations").status_code == 403
    response, _ = _ask(client, "¿Quién es Juan Perez?")
    assert response.status_code == 403
    assert fake_ollama == []


def test_chief_without_scope_gets_no_documents(firm, fake_ollama):
    web, ids = firm
    response, _ = _ask(_client_as(web, ids["chief"]), "¿Quién es Juan Perez?")
    assert response.status_code == 403
    assert fake_ollama == []


def test_assistant_retrieves_only_authorized_documents_with_sources(firm, fake_ollama):
    web, ids = firm
    grant(web, ids["chief"], "firm")
    response, cid = _ask(_client_as(web, ids["chief"]), "¿Qué dicen los documentos sobre Juan Perez?")
    assert response.status_code == 200
    events = _events(response)
    done = [e for e in events if e["type"] == "done"][0]
    sent = " ".join(fake_ollama[0]["docs"])
    assert "reservado.txt" not in sent                       # restringido: nunca llega al modelo
    assert "contrato.txt" in sent and "carta.txt" in sent    # recupera de varios expedientes
    assert "DISTINTOS expedientes" in fake_ollama[0]["system"]
    doc_sources = [s for s in done["sources"] if s["source_type"] == "document"]
    assert {s["case_id"] for s in doc_sources} == {ids["case1"], ids["case2"]}
    assert all(s["document_id"] in (ids["d1"], ids["d2"]) and s["page_start"] == 1 for s in doc_sources)


def test_case_filter_cannot_extend_scope(firm, fake_ollama):
    web, ids = firm
    grant(web, ids["chief"], "case", ids["case1"])
    response, _ = _ask(_client_as(web, ids["chief"]), "Juan Perez", case_ids=[ids["case2"]])
    assert response.status_code == 403             # el caso 2 no está en su alcance
    response, _ = _ask(_client_as(web, ids["chief"]), "Juan Perez", case_ids=[ids["case1"], ids["case2"]])
    assert response.status_code == 200
    assert all("carta.txt" not in d for d in fake_ollama[-1]["docs"])


def test_assistant_scope_permission_limits_paths(firm, fake_ollama):
    web, ids = firm
    grant(web, ids["chief"], "firm")
    with web.connect_db() as db:
        db.execute("INSERT INTO user_permissions(user_id, permission, effect) VALUES (?, 'assistant.firm_access', 'deny')",
                   (ids["chief"],))
    response, _ = _ask(_client_as(web, ids["chief"]), "Juan Perez")
    assert response.status_code == 403     # tiene alcance de firma, pero el asistente no puede usarlo


def test_conversations_are_private_to_their_owner(firm, fake_ollama):
    web, ids = firm
    grant(web, ids["chief"], "firm")
    grant(web, ids["chief2"], "firm")
    _response, cid = _ask(_client_as(web, ids["chief"]), "Juan Perez")
    intruder = _client_as(web, ids["chief2"])
    assert intruder.get(f"/api/assistant/conversations/{cid}/messages").status_code == 403
    assert intruder.post(f"/api/assistant/conversations/{cid}/ask", json={"question": "hola"},
                         headers={"X-CSRF-Token": CSRF}).status_code == 403
    assert intruder.get("/api/assistant/conversations").get_json()["conversations"] == []


def test_answers_are_redacted_after_permission_revocation(firm, fake_ollama):
    web, ids = firm
    grant(web, ids["chief"], "firm")
    client = _client_as(web, ids["chief"])
    _response, cid = _ask(client, "Juan Perez")
    before = client.get(f"/api/assistant/conversations/{cid}/messages").get_json()["messages"]
    assert before[-1]["content"] == "respuesta simulada" and before[-1]["sources"]
    with web.connect_db() as db:
        db.execute("DELETE FROM access_grants WHERE user_id = ?", (ids["chief"],))
        db.execute("INSERT INTO access_grants(user_id, scope_type, scope_id) VALUES (?, 'case', ?)",
                   (ids["chief"], ids["case2"]))
    after = client.get(f"/api/assistant/conversations/{cid}/messages").get_json()["messages"]
    assert after[-1]["redacted"] is True
    assert "respuesta simulada" not in after[-1]["content"] and after[-1]["sources"] == []


def test_assistant_history_is_separate_from_case_chat(firm, fake_ollama):
    web, ids = firm
    grant(web, ids["chief"], "firm")
    _ask(_client_as(web, ids["chief"]), "Juan Perez")
    with web.connect_db() as db:
        assert db.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM assistant_messages").fetchone()[0] == 2
        stored = db.execute("SELECT content FROM assistant_messages").fetchone()[0]
    assert stored.startswith("enc:")      # cifrado en reposo como el chat por expediente


def test_firm_index_cache_is_per_user(firm, fake_ollama):
    web, ids = firm
    grant(web, ids["chief"], "firm")
    grant(web, ids["chief2"], "case", ids["case2"])
    _ask(_client_as(web, ids["chief"]), "Juan Perez")
    _ask(_client_as(web, ids["chief2"]), "Juan Perez")
    keys = list(web.rt.assistant._cache)
    assert {k[0] for k in keys} == {ids["chief"], ids["chief2"]}
    assert keys[0][1] != keys[1][1]
    assert all("contrato.txt" not in d for d in fake_ollama[-1]["docs"])


def test_case_chat_index_and_answers_do_not_leak_between_users(firm, fake_ollama):
    web, ids = firm
    a = admin_id(web)
    with web.connect_db() as db:
        db.execute("INSERT INTO document_acl(document_id, user_id, effect) VALUES (?, ?, 'allow')", (ids["sec"], a))
    question = {"question": "¿Qué deuda tiene Juan Perez?"}
    admin_resp = _client_as(web, a).post(f"/api/case/{ids['case1']}/chat", json=question, headers={"X-CSRF-Token": CSRF})
    assert admin_resp.status_code == 200 and "reservado.txt" in " ".join(fake_ollama[-1]["docs"])
    lawyer_resp = _client_as(web, ids["lawyer"]).post(f"/api/case/{ids['case1']}/chat", json=question,
                                                      headers={"X-CSRF-Token": CSRF})
    assert lawyer_resp.status_code == 200
    body = lawyer_resp.get_data(as_text=True)
    assert "reservado.txt" not in body and '"cached": true' not in body
    assert "reservado.txt" not in " ".join(fake_ollama[-1]["docs"])
    signatures = {k[1] for k in web.indexer._index_cache}
    assert len(signatures) == 2               # un índice por conjunto autorizado
    assert all(key[2] in (a, ids["lawyer"]) for key in web.indexer._answer_cache)


def test_partial_index_is_not_used_when_it_exceeds_user_scope(firm, fake_ollama):
    web, ids = firm
    with web.connect_db() as db:
        db.execute("INSERT INTO document_acl(document_id, user_id, effect) VALUES (?, ?, 'deny')", (ids["d1"], ids["lawyer"]))
        doc = db.execute("SELECT stored_path FROM documents WHERE id = ?", (ids["d1"],)).fetchone()[0]
    web.indexer._jobs[ids["case1"]] = {"state": "running", "progress": .5, "message": ""}
    web.indexer._partial[ids["case1"]] = (object(), 1, 2, (doc,))
    response = _client_as(web, ids["lawyer"]).post(f"/api/case/{ids['case1']}/chat", json={"question": "renta"},
                                                   headers={"X-CSRF-Token": CSRF})
    # Al abogado solo le queda reservado.txt (restringido, sin excepción) => no tiene documentos.
    assert response.status_code == 400


def test_case_history_hides_answers_citing_revoked_documents(firm, fake_ollama):
    web, ids = firm
    from vexa.database import store
    store.add_message(web.db_path, ids["case1"], ids["lawyer"], "assistant", "La renta es 450000", ["contrato.txt — página 1"])
    client = _client_as(web, ids["lawyer"])
    assert client.get(f"/api/case/{ids['case1']}/history").get_json()["messages"][0]["content"] == "La renta es 450000"
    with web.connect_db() as db:
        db.execute("INSERT INTO document_acl(document_id, user_id, effect) VALUES (?, ?, 'deny')", (ids["d1"], ids["lawyer"]))
    hidden = client.get(f"/api/case/{ids['case1']}/history").get_json()["messages"][0]
    assert "450000" not in hidden["content"] and hidden["sources"] == ""


def test_ollama_error_message_does_not_leak_internal_details():
    message = case_routes.ollama_error_message(RuntimeError("C:\\secreto\\traza"))
    assert "secreto" not in message
