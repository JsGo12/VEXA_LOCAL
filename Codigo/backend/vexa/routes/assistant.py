"""Asistente IA transversal (abogado jefe u otros usuarios con assistant.use)."""
from __future__ import annotations

import json
import logging
import time

from flask import Blueprint, Response, abort, g, jsonify, render_template, request, stream_with_context

from vexa import runtime
from vexa.permissions import can, deny, permission_required
from vexa.rag import firm
from vexa.rag import hybrid as rag_hybrid
from vexa.routes.cases import chat_profile, ollama_error_message
from vexa.services import audit

bp = Blueprint("assistant", __name__)
LOGGER = logging.getLogger(__name__)


def _event(kind, **data):
    return json.dumps({"type": kind, **data}, ensure_ascii=False) + "\n"


def _own_conversation(conversation_id: int) -> None:
    if not runtime().assistant.owns(g.user["id"], conversation_id):
        deny("assistant.conversation", "conversación ajena o inexistente", "assistant_conversation", conversation_id)


@bp.get("/assistant")
@permission_required("assistant.use")
def page():
    return render_template("assistant.html")


@bp.get("/api/assistant/scope")
@permission_required("assistant.use")
def scope():
    documents, cards, case_scope = runtime().assistant.authorized_material(g.user)
    counts = {}
    for d in documents:
        counts[d.case_id] = counts.get(d.case_id, 0) + 1
    return jsonify(cases=[{"id": c.case_id, "label": c.label, "documents": counts.get(c.case_id, 0),
                           "via": sorted(case_scope.get(c.case_id, []))} for c in cards])


@bp.get("/api/assistant/conversations")
@permission_required("assistant.use")
def list_conversations():
    return jsonify(conversations=runtime().assistant.conversations(g.user["id"]))


@bp.post("/api/assistant/conversations")
@permission_required("assistant.use")
def create_conversation():
    payload = request.get_json(silent=True) or {}
    conversation_id = runtime().assistant.create_conversation(g.user["id"], str(payload.get("title", "")))
    audit.record("assistant.conversation_create", "ok", resource_type="assistant_conversation",
                 resource_id=conversation_id)
    return jsonify(ok=True, id=conversation_id)


@bp.get("/api/assistant/conversations/<int:conversation_id>/messages")
@permission_required("assistant.use")
def conversation_messages(conversation_id):
    _own_conversation(conversation_id)
    return jsonify(messages=runtime().assistant.messages(g.user, conversation_id))


@bp.post("/api/assistant/conversations/<int:conversation_id>/delete")
@permission_required("assistant.use")
def delete_conversation(conversation_id):
    _own_conversation(conversation_id)
    runtime().assistant.delete_conversation(g.user["id"], conversation_id)
    audit.record("assistant.conversation_delete", "ok", resource_type="assistant_conversation",
                 resource_id=conversation_id)
    return jsonify(ok=True)


@bp.post("/api/assistant/conversations/<int:conversation_id>/ask")
@permission_required("assistant.use")
def ask(conversation_id):
    started = time.perf_counter()
    _own_conversation(conversation_id)
    rt = runtime()
    payload = request.get_json(silent=True) or {}
    question = str(payload.get("question", "")).strip()[:2000]
    if not question:
        return jsonify(ok=False, error="Escribe una consulta."), 400
    case_filter = payload.get("case_ids")
    if case_filter is not None:
        if not isinstance(case_filter, list) or not all(isinstance(c, int) for c in case_filter):
            abort(400, "case_ids debe ser una lista de números.")
    documents, cards, scope = rt.assistant.authorized_material(g.user, case_filter)
    if not cards:
        audit.record("assistant.query", "denied", resource_type="assistant_conversation",
                     resource_id=conversation_id, reason="sin expedientes autorizados para el asistente")
        return jsonify(ok=False, error="No tienes expedientes autorizados para el asistente. Solicita un "
                                       "alcance (firma, equipo o caso) a un administrador."), 403
    perfil, error = chat_profile()
    if error:
        return error
    history = rt.assistant.history_for_model(g.user, conversation_id)
    user = g.user
    can_download = can("documents.download")
    audit.record("assistant.query", "ok", resource_type="assistant_conversation", resource_id=conversation_id,
                 details={"expedientes": len(cards), "documentos": len(documents)})

    @stream_with_context
    def generate():
        try:
            yield _event("status", text=f"Buscando en {len(cards)} expediente(s) autorizados…")
            index = rt.assistant.index_for(user["id"], documents)
            standalone = rag_hybrid.reformular_pregunta(question, history, perfil.modelo)
            fragments = firm.retrieve(standalone, index, cards, documents, perfil.max_chars)
            if not fragments:
                text = "No encontré información relacionada en los expedientes autorizados."
                rt.assistant.add_message(conversation_id, "user", question)
                rt.assistant.add_message(conversation_id, "assistant", text)
                yield _event("delta", text=text)
                yield _event("done", sources=[])
                return
            sources = firm.sources_for(fragments, documents, cards)
            parts = []
            for text in firm.stream_answer(standalone, fragments, history, perfil.modelo, perfil.opciones):
                parts.append(text)
                yield _event("delta", text=text)
            answer = "".join(parts)
            rt.assistant.add_message(conversation_id, "user", question)
            rt.assistant.add_message(conversation_id, "assistant", answer, sources,
                                     metadata={"modelo": perfil.modelo, "expedientes": len(cards)})
            for s in sources:
                s["downloadable"] = bool(can_download and s.get("document_id"))
            LOGGER.info("Asistente usuario=%s expedientes=%s documentos=%s fragmentos=%s total_ms=%.0f",
                        user["id"], len(cards), len(documents), len(fragments),
                        (time.perf_counter() - started) * 1000)
            yield _event("done", sources=sources)
        except Exception as exc:
            LOGGER.exception("Error en el asistente transversal")
            yield _event("error", error=ollama_error_message(exc))

    return Response(generate(), mimetype="application/x-ndjson",
                    headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})
