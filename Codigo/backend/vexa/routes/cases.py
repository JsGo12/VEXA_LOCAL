"""Paneles de casos, espacio del expediente, descargas y chat individual por expediente."""
from __future__ import annotations

import io
import logging
import time
import zipfile
from pathlib import Path

from flask import Blueprint, flash, g, jsonify, redirect, render_template, request, send_file, url_for
from werkzeug.utils import secure_filename

from vexa import runtime
from vexa.database import connect, store
from vexa.permissions import can, login_required, policy, require_case, require_document, visible_documents
from vexa.rag import core as rag_core
from vexa.rag import formats
from vexa.rag import hybrid as rag_hybrid
from vexa.rag import stages as rag_stages
from vexa.security import vault
from vexa.services import audit
from vexa.services import cases as case_service
from vexa.services import messages as message_service
from vexa.services import notifications as notification_service
from vexa.services import llm_priority
from vexa.routes.streaming import chat_profile, event as _event, ndjson_response, ollama_error_message
from vexa.services.audit_view import local_time
from vexa.services.indexing import document_paths

bp = Blueprint("cases", __name__)
LOGGER = logging.getLogger(__name__)
NO_RESULTS = ("No encontré información relacionada en este expediente. Prueba con un nombre, fecha, monto "
              "o frase que aparezca en el documento.")


def _my_cases():
    with connect(runtime().settings.db_path) as db:
        scope = policy.case_scope(db, g.user) if policy.has_permission(db, g.user, "cases.view") else {}
    return case_service.cases_by_ids(runtime().settings.db_path, scope)


# ------------------------------------------------------------------- paneles
@bp.get("/lawyer")
@login_required
def lawyer_dashboard():
    return render_template("lawyer.html", cases=_my_cases())


@bp.get("/chief")
@login_required
def chief_dashboard():
    if not (can("assistant.use") or can("cases.manage")):
        return redirect(url_for("cases.lawyer_dashboard"))
    settings = runtime().settings
    with connect(settings.db_path) as db:
        assistant_cases = len(policy.assistant_scope(db, g.user))
        totals = None
        if policy.has_permission(db, g.user, "cases.manage"):
            totals = {
                "cases": db.execute("SELECT COUNT(*) FROM cases").fetchone()[0],
                "lawyers": db.execute("SELECT COUNT(*) FROM users WHERE active = 1 AND role <> 'admin'").fetchone()[0],
                "teams": db.execute("SELECT COUNT(*) FROM teams").fetchone()[0],
            }
    return render_template("chief.html", cases=_my_cases(), assistant_cases=assistant_cases, totals=totals)


# -------------------------------------------------------------------- expediente
def _summary_visible(case_id: int, visible) -> bool:
    """El resumen automático usa los documentos no restringidos: se muestra solo si el usuario los ve todos."""
    with connect(runtime().settings.db_path) as db:
        common = {d["id"] for d in policy.unrestricted_documents(db, case_id)}
    return common <= {d["id"] for d in visible}


@bp.get("/case/<int:case_id>")
@login_required
def case_workspace(case_id):
    case = require_case(case_id)
    documents = visible_documents(case_id)
    rt = runtime()
    if any(Path(doc["stored_path"]).is_file() for doc in documents):
        rt.indexer.schedule(case_id)
    case_summary = case["summary"]
    if not case_summary and documents:
        try:
            case_summary = case_service.preview_text(documents[0])
        except Exception:
            LOGGER.exception("No se pudo generar una vista previa para el caso %s", case_id)
    audit.record("cases.open", "ok", resource_type="case", resource_id=case_id)
    watch_dir = str(rt.settings.watch_dir / str(case_id)) if can("cases.manage") else None
    team, unread, panel = [], 0, request.args.get("panel", "")
    if can("cases.message"):
        team = message_service.thread(rt.settings.db_path, case_id, g.user["id"])
        if panel == "mensajes":
            message_service.mark_read(rt.settings.db_path, case_id, g.user["id"])
        unread = message_service.unread_count(rt.settings.db_path, case_id, g.user["id"])
    return render_template("case.html", case=case, documents=documents, case_summary=case_summary,
                           watch_dir=watch_dir, can_download=can("documents.download"),
                           updates=case_service.case_updates(rt.settings.db_path, case_id),
                           status_labels=case_service.STATUS_LABELS, close_reasons=case_service.CLOSE_REASONS,
                           max_mb=rt.settings.max_file_size // (1024 * 1024),
                           team_messages=[{**m, "when": local_time(m["created_at"])} for m in team],
                           messages_unread=unread, quick_messages=message_service.QUICK_MESSAGES,
                           open_panel="mensajes" if panel == "mensajes" else "ia")


@bp.post("/case/<int:case_id>/progress")
@login_required
def update_progress(case_id):
    require_case(case_id, "cases.update_progress")
    try:
        status, progress, note, reason = case_service.parse_progress(
            request.form.get("status", ""), request.form.get("progress", ""), request.form.get("note", ""),
            request.form.get("close_reason", ""))
        case_service.update_progress(runtime().settings.db_path, case_id, g.user["id"], status, progress, note,
                                     reason)
        notification_service.progress_updated(runtime().settings.db_path, case_id, g.user["id"],
                                              case_service.close_label(status, reason), progress)
        message_service.system(runtime().settings.db_path, case_id,
                               f"{g.user['name']} actualizó el avance: {case_service.close_label(status, reason)}, {progress} %.")
        audit.record("cases.progress_update", "ok", resource_type="case", resource_id=case_id,
                     details={"estado": status, "avance": progress, "con_nota": bool(note),
                              **({"motivo": reason} if reason else {})})
        flash("Avance del caso actualizado.", "success")
    except case_service.CaseError as exc:
        flash(str(exc), "error")
    return redirect(url_for("cases.case_workspace", case_id=case_id) + "#avance")


@bp.post("/case/<int:case_id>/notes")
@login_required
def add_note(case_id):
    """Nota o evidencia del abogado: queda en el historial sin cambiar estado ni porcentaje."""
    require_case(case_id, "cases.add_note")
    note = request.form.get("note", "")
    try:
        case_service.add_note(runtime().settings.db_path, case_id, g.user["id"], note)
        notification_service.note_added(runtime().settings.db_path, case_id, g.user["id"], g.user["name"])
        message_service.system(runtime().settings.db_path, case_id, f"{g.user['name']} registró una nota de avance.")
        audit.record("cases.note_add", "ok", resource_type="case", resource_id=case_id)
        flash("Nota registrada en el historial del caso.", "success")
    except case_service.CaseError as exc:
        flash(str(exc), "error")
    return redirect(url_for("cases.case_workspace", case_id=case_id) + "#avance")


@bp.get("/case/<int:case_id>/expediente.zip")
@login_required
def download_case(case_id):
    """Expediente completo en ZIP: solo los documentos que el usuario puede descargar."""
    case = require_case(case_id)
    with connect(runtime().settings.db_path) as db:
        documents = [d for d in policy.visible_documents(db, g.user, case_id)
                     if policy.document_allowed(db, g.user, d, "documents.download")]
    if not documents:
        audit.record("cases.download", "denied", resource_type="case", resource_id=case_id,
                     reason="sin documentos descargables")
        return render_template("error.html", code="403", message="No tienes documentos descargables en este caso."), 403
    buffer, used, included = io.BytesIO(), set(), 0
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for document in documents:
            if not Path(document["stored_path"]).is_file():
                continue
            try:
                content = vault.read_bytes(document["stored_path"])
            except Exception:
                LOGGER.error("No se pudo descifrar el documento %s", document["id"])
                continue
            name, n = document["original_name"], 1
            while name.lower() in used:           # nombres repetidos: «archivo (2).pdf»
                stem, dot, ext = document["original_name"].rpartition(".")
                n += 1
                name = f"{stem} ({n}).{ext}" if dot else f"{document['original_name']} ({n})"
            used.add(name.lower())
            archive.writestr(name, content)
            included += 1
    audit.record("cases.download", "ok", resource_type="case", resource_id=case_id,
                 details={"documentos": included})
    buffer.seek(0)
    label = secure_filename(case["reference"] or case["title"]) or f"caso-{case_id}"
    return send_file(buffer, as_attachment=True, download_name=f"expediente-{label}.zip", mimetype="application/zip")


# Destinos permitidos tras subir documentos (lista fija: nunca una URL recibida del formulario).
_UPLOAD_RETURN = {"admin": "admin.dashboard", "seguimiento": "admin.follow_up"}


def upload_reply(response):
    """Las subidas con barra de progreso (js/upload.js) piden JSON: devuelve a dónde ir en vez de redirigir.

    El mensaje (flash) ya quedó en la sesión, así que se muestra al cargar ese destino."""
    if request.headers.get("X-Requested-With") == "vexa-upload" and response.status_code in (301, 302, 303):
        return jsonify(ok=True, redirect=response.location)
    return response


def _after_upload(case_id: int):
    endpoint = _UPLOAD_RETURN.get(request.form.get("next", ""))
    return upload_reply(redirect(url_for(endpoint) if endpoint else url_for("cases.case_workspace", case_id=case_id)))


@bp.post("/case/<int:case_id>/documents")
@login_required
def upload_documents(case_id):
    require_case(case_id, "documents.upload")
    rt = runtime()
    settings = rt.settings
    uploads = [item for item in request.files.getlist("documents") if item and item.filename]
    try:
        if not uploads:
            raise case_service.CaseError("Selecciona al menos un documento.")
        files = []
        for uploaded in uploads:
            content = uploaded.read(settings.max_file_size + 1)
            files.append((case_service.validate_upload(uploaded.filename, content, settings.max_file_size), content))
    except case_service.CaseError as exc:
        flash(str(exc), "error")
        return _after_upload(case_id)
    restricted = 1 if request.form.get("restricted") == "1" and can("permissions.manage") else 0
    ids = []
    for name, content in files:
        doc_id = case_service.add_document(settings.db_path, settings.upload_dir, case_id, name, content, g.user["id"])
        if restricted:
            with connect(settings.db_path) as db:
                db.execute("UPDATE documents SET restricted = 1 WHERE id = ?", (doc_id,))
        ids.append(doc_id)
    notification_service.documents_added(settings.db_path, case_id, g.user["id"], len(ids))
    message_service.system(settings.db_path, case_id,
                           f"{g.user['name']} agregó {len(ids)} documento(s) al expediente.")
    audit.record("documents.upload", "ok", resource_type="case", resource_id=case_id,
                 details={"documentos": ids, "restringidos": bool(restricted)})
    rt.indexer.schedule(case_id)
    flash(f"{len(ids)} documento(s) agregado(s). Se están preparando en segundo plano.", "success")
    return _after_upload(case_id)


@bp.get("/documents/<int:document_id>")
@login_required
def download_document(document_id):
    document = require_document(document_id, "documents.download")
    if not Path(document["stored_path"]).is_file():
        return render_template("error.html", code="404", message="El archivo ya no está disponible."), 404
    try:
        content = vault.read_bytes(document["stored_path"])
    except Exception:
        LOGGER.error("No se pudo descifrar el documento %s", document_id)
        audit.record("documents.download", "error", resource_type="document", resource_id=document_id,
                     reason="no se pudo descifrar")
        return render_template("error.html", code="500", message="No se pudo leer el documento cifrado."), 500
    audit.record("documents.download", "ok", resource_type="document", resource_id=document_id,
                 details={"caso": document["case_id"]})
    return send_file(io.BytesIO(content), as_attachment=True, download_name=document["original_name"])


@bp.get("/api/case/<int:case_id>/status")
@login_required
def case_status(case_id):
    require_case(case_id)
    return jsonify(**runtime().indexer.job(case_id))


def _denied_names(case_id: int, visible) -> set:
    """Nombres de documentos del caso que el usuario NO puede ver (ante nombres repetidos, se oculta de más)."""
    visible_ids = {d["id"] for d in visible}
    with connect(runtime().settings.db_path) as db:
        rows = db.execute("SELECT id, original_name FROM documents WHERE case_id = ?", (case_id,)).fetchall()
    return {r["original_name"] for r in rows if r["id"] not in visible_ids}


@bp.get("/api/case/<int:case_id>/history")
@login_required
def case_history(case_id):
    require_case(case_id)
    hidden = _denied_names(case_id, visible_documents(case_id))
    messages = store.recent_messages(runtime().settings.db_path, case_id, g.user["id"], limit=40)
    for m in messages:   # respuestas que citan documentos que ya no puede ver se ocultan
        if m["role"] == "assistant" and any(m["sources"].startswith(n + " ") or f"| {n} " in m["sources"]
                                            for n in hidden):
            m.update(content="[Respuesta oculta: cita un documento al que ya no tienes acceso.]", sources="")
    return jsonify(messages=messages)


@bp.post("/api/case/<int:case_id>/history/clear")
@login_required
def case_history_clear(case_id):
    require_case(case_id)
    store.clear_messages(runtime().settings.db_path, case_id, g.user["id"])
    return jsonify(ok=True)


@bp.get("/api/case/<int:case_id>/summary")
@login_required
def case_summary_api(case_id):
    require_case(case_id)
    if not _summary_visible(case_id, visible_documents(case_id)):
        return jsonify(summary=None)
    row = store.get_summary(runtime().settings.db_path, case_id)
    return jsonify(summary=row[1] if row else None)


# -------------------------------------------------------------------- chat
@bp.post("/api/case/<int:case_id>/chat")
@login_required
def case_chat(case_id):
    request_started = time.perf_counter()
    require_case(case_id, "documents.view")
    rt = runtime()
    db_path = rt.settings.db_path
    payload = request.get_json(silent=True) or {}
    question = str(payload.get("question", "")).strip()[:2000]
    if not question:
        return jsonify(ok=False, error="Escribe una consulta."), 400
    visible = visible_documents(case_id)
    paths, names = document_paths(visible)
    if not paths:
        return jsonify(ok=False, error="Este caso no tiene documentos disponibles para ti."), 400

    perfil, error = chat_profile()
    if error:
        return error
    notice = ""
    job, part = rt.indexer.partial(case_id)
    if job and job["state"] == "running":
        # Se puede preguntar mientras indexa, solo si el índice parcial no excede lo autorizado.
        if not part or not set(part[3]) <= set(paths):
            pct = int(job["progress"] * 100)
            return jsonify(ok=False, error=f"VEXA está preparando los documentos ({pct}%). Inténtalo en unos segundos."), 409
        index, done, total, _ = part
        signature, index_cache_hit = None, False
        notice = f"Aviso: VEXA aún indexa; esta respuesta usa {done} de {total} documentos.\n\n"
    else:
        try:
            index, signature, index_cache_hit = rt.indexer.get_index(case_id, paths, names)
        except Exception:
            LOGGER.exception("Falló la extracción o indexación del caso %s", case_id)
            return jsonify(ok=False, error="VEXA no pudo leer o preparar los documentos del caso. Revisa que los archivos sean válidos."), 422

    if index.esta_vacio():
        errors = getattr(index, "errores", [])
        if errors:
            message = "No se pudo leer ningún documento: " + "; ".join(errors[:3])
        else:
            extra = "" if formats.ocr_disponible() else " Si el PDF es escaneado, instala Tesseract para activar el OCR."
            message = "VEXA no pudo extraer texto de los documentos." + extra
        return jsonify(ok=False, error=message), 422

    user_id = g.user["id"]
    history = store.recent_messages(db_path, case_id, user_id, limit=rag_hybrid.HISTORY_TURNS * 2)
    with llm_priority.interactive():
        standalone = rag_hybrid.reformular_pregunta(question, history, perfil.modelo)

    answer_key = None
    if signature is not None:
        answer_key = (case_id, signature, user_id, " ".join(standalone.casefold().split()), perfil.modelo)
        cached = rt.indexer.cached_answer(answer_key)
        if cached is not None:
            answer, sources = cached
            store.add_message(db_path, case_id, user_id, "user", question)
            store.add_message(db_path, case_id, user_id, "assistant", answer, sources)
            return jsonify(ok=True, answer=answer, sources=sources, cached=True)

    staged = rag_stages.es_totalidad(standalone)
    fragments, stage_chunks = [], []
    try:
        if staged:
            stage_chunks = rag_hybrid.buscar_todos_relevantes(standalone, index)
        else:
            top_k = rag_core.determinar_top_k(standalone, len(index.chunks))
            hits = rag_hybrid.buscar_hibrido(standalone, index, top_k=top_k)
            fragments = rag_hybrid.limitar_contexto(rag_hybrid.con_vecinos(hits, index), hits, perfil.max_chars)
    except Exception:
        LOGGER.exception("Falló la búsqueda documental del caso %s", case_id)
        return jsonify(ok=False, error="Falló la búsqueda dentro de los documentos. Revisa el registro del servidor."), 500
    if not (stage_chunks if staged else fragments):
        return jsonify(ok=False, error=NO_RESULTS), 422

    def generate():
        generation_started = time.perf_counter()
        parts = []
        sources = list(dict.fromkeys(f.fuente for f in (stage_chunks if staged else fragments)))
        try:
            if notice:
                yield _event("delta", text=notice)       # se muestra, pero no entra al historial
            if staged:
                for ev in rag_stages.responder_por_etapas(standalone, index, perfil.modelo, perfil.opciones,
                                                          perfil.max_chars, chunks=stage_chunks):
                    if ev["type"] == "delta":
                        parts.append(ev["text"]); yield _event("delta", text=ev["text"])
                    elif ev["type"] == "progress":
                        yield _event("progress", done=ev["done"], total=ev["total"])
                    elif ev["type"] == "sources":
                        sources = ev["sources"]
            else:
                for text in rag_hybrid.consultar_stream(standalone, fragments, history, modelo=perfil.modelo,
                                                        opciones=perfil.opciones):
                    parts.append(text)
                    yield _event("delta", text=text)
            answer = "".join(parts)
            if answer_key is not None:
                rt.indexer.store_answer(answer_key, (answer, sources))
            store.add_message(db_path, case_id, user_id, "user", question)
            store.add_message(db_path, case_id, user_id, "assistant", answer, sources)
            LOGGER.info("Consulta RAG caso=%s modelo=%s etapas=%s semantico=%s index_cache=%s chunks=%s "
                        "contexto=%s reformulada=%s generacion_ms=%.0f total_ms=%.0f",
                        case_id, perfil.modelo, staged, index.semantico, index_cache_hit, len(index.chunks),
                        len(fragments), standalone != question, (time.perf_counter() - generation_started) * 1000,
                        (time.perf_counter() - request_started) * 1000)
            yield _event("done", sources=sources, cached=False)
        except Exception as exc:
            LOGGER.exception("Error al consultar caso %s", case_id)
            yield _event("error", error=ollama_error_message(exc))

    return ndjson_response(generate())
