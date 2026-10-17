import hashlib
import os

import formats
import rag_hybrid
import rag_core
import vault
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from test_security import CSRF, _client_as, _seed_case, _web_app


def test_empty_scanned_pdf_is_reported_without_ocr(monkeypatch):
    class Page:
        def extract_text(self):
            return None

    class Pdf:
        pages = [Page()]

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(formats.pdfplumber, "open", lambda _data: Pdf())
    monkeypatch.setattr(formats, "ocr_disponible", lambda: False)

    assert formats.extraer("escaneado.pdf", b"pdf simulado") == []


def test_corrupt_pdf_does_not_block_other_documents(monkeypatch, tmp_path):
    valid = tmp_path / "valido.txt"
    corrupt = tmp_path / "roto.pdf"
    valid.write_text("Texto válido para indexar.", encoding="utf-8")
    corrupt.write_bytes(b"esto no es un PDF")
    monkeypatch.setattr(rag_hybrid, "_embed", lambda *_args: None)

    index = rag_hybrid.construir_indice_hibrido([str(corrupt), str(valid)])

    assert not index.esta_vacio()
    assert any("roto.pdf" in error and "error al procesar" in error for error in index.errores)
    assert any("Texto válido" in chunk.text for chunk in index.chunks)


def test_ollama_down_returns_actionable_error_before_chat(monkeypatch, tmp_path):
    web = _web_app(monkeypatch, tmp_path)
    _assigned_id, other_id, case_id, _document_id = _seed_case(web, tmp_path)
    client = _client_as(web, other_id)
    monkeypatch.setattr(web, "case_access", lambda _case_id: None)
    monkeypatch.setattr(web.model_select, "instalados_ollama", lambda: (_ for _ in ()).throw(ConnectionError()))

    response = client.post(
        f"/api/case/{case_id}/chat", json={"question": "Consulta"},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 503
    assert "Ollama no responde" in response.get_json()["error"]


def test_chat_reports_missing_model_instead_of_starting_generation(monkeypatch, tmp_path):
    web = _web_app(monkeypatch, tmp_path)
    _assigned_id, other_id, case_id, _document_id = _seed_case(web, tmp_path)
    client = _client_as(web, other_id)
    monkeypatch.setattr(web, "case_access", lambda _case_id: None)
    monkeypatch.setattr(web.model_select, "instalados_ollama", set)
    monkeypatch.setattr(web.model_select, "hardware", lambda: (8, 0))

    response = client.post(
        f"/api/case/{case_id}/chat", json={"question": "Consulta"},
        headers={"X-CSRF-Token": CSRF},
    )

    assert response.status_code == 503
    assert "ollama pull" in response.get_json()["error"]


def test_watched_file_larger_than_limit_is_rejected(monkeypatch, tmp_path):
    web = _web_app(monkeypatch, tmp_path)
    _assigned_id, _other_id, case_id, _document_id = _seed_case(web, tmp_path)
    watched = tmp_path / "grande.txt"
    watched.write_bytes(b"123456")
    monkeypatch.setattr(web, "MAX_FILE_SIZE", 5)

    assert web._ingest_file(case_id, watched) is False
    with web.connect_db() as db:
        assert db.execute("SELECT COUNT(*) FROM documents WHERE case_id=?", (case_id,)).fetchone()[0] == 1


def test_index_job_with_no_paths_finishes_as_error_and_clears_partial(monkeypatch, tmp_path):
    web = _web_app(monkeypatch, tmp_path, disable_background_index=False)
    monkeypatch.setattr(web, "_rutas_caso", lambda _case_id: ([], {}))
    web._partial[501] = (object(), 1, 1)

    web._precargar_indice(501)

    assert web._jobs[501]["state"] == "error"
    assert 501 not in web._partial


def test_different_cases_index_concurrently_and_build_locks_are_released(monkeypatch, tmp_path):
    web = _web_app(monkeypatch, tmp_path)
    first = tmp_path / "uno.txt"
    second = tmp_path / "dos.txt"
    first.write_text("texto uno", encoding="utf-8")
    second.write_text("texto dos", encoding="utf-8")
    barrier = Barrier(2)

    with web._rag_cache_lock:
        web._index_cache.clear()
        web._answer_cache.clear()
    with web._build_locks_guard:
        web._build_locks.clear()
    monkeypatch.setattr(web, "_rutas_caso", lambda _case_id: ([], {}))

    def build(paths, **_kwargs):
        barrier.wait(timeout=4)
        chunk = rag_core.Chunk(paths[0], 1, 0, "texto de prueba")
        return rag_hybrid._armar([chunk], None, set(), rag_hybrid.EMBED_MODEL)

    monkeypatch.setattr(web.rag_hybrid, "construir_indice_hibrido", build)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(web._obtener_indice_caso, 9101, [str(first)]),
            pool.submit(web._obtener_indice_caso, 9102, [str(second)]),
        ]
        results = [future.result(timeout=6) for future in futures]

    assert all(result[0].chunks for result in results)
    assert web._build_locks == {}


def test_document_hash_change_invalidates_index_cache_even_with_same_stat(monkeypatch, tmp_path):
    web = _web_app(monkeypatch, tmp_path)
    _assigned_id, _other_id, case_id, _document_id = _seed_case(web, tmp_path)
    paths, _names = web._rutas_caso(case_id)
    stored = paths[0]
    before = os.stat(stored)
    build_count = []

    def fake_build(_paths, **_kwargs):
        build_count.append(True)
        chunk = rag_core.Chunk("contrato.txt", 1, 0, "Texto de prueba.")
        return rag_hybrid._armar([chunk], None, set(), rag_hybrid.EMBED_MODEL)

    monkeypatch.setattr(web.rag_hybrid, "construir_indice_hibrido", fake_build)
    _first_index, first_signature, first_hit = web._obtener_indice_caso(case_id, paths)
    assert not first_hit

    updated = b"Texto de cambio del contrato."
    assert len(updated) == len(b"Texto de prueba del contrato.")
    vault.write_encrypted(stored, updated)
    os.utime(stored, ns=(before.st_atime_ns, before.st_mtime_ns))
    with web.connect_db() as db:
        db.execute("UPDATE documents SET sha256=? WHERE case_id=?", (hashlib.sha256(updated).hexdigest(), case_id))

    _second_index, second_signature, second_hit = web._obtener_indice_caso(case_id, paths)

    assert not second_hit
    assert first_signature != second_signature
    assert len(build_count) == 2
