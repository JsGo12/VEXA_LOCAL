"""Piezas comunes del chat del expediente y del asistente transversal: eventos NDJSON, estado de
Ollama y mensajes de error legibles. No es un blueprint."""
from __future__ import annotations

import json

from flask import Response, jsonify, stream_with_context

from vexa.rag import core as rag_core
from vexa.rag import model_select
from vexa.services import llm_priority


def event(kind: str, **data) -> str:
    """Una línea NDJSON: {"type": kind, ...}."""
    return json.dumps({"type": kind, **data}, ensure_ascii=False) + "\n"


def ndjson_response(events) -> Response:
    """Respuesta en streaming. Mientras dura, el trabajo de fondo (resúmenes) espera su turno.

    Si el navegador corta la conexión (botón Detener o tiempo límite), Flask cierra el generador:
    se sale de `interactive()` y los generadores internos cierran el stream de Ollama.
    """
    @stream_with_context
    def generate():
        with llm_priority.interactive():
            yield from events

    return Response(generate(), mimetype="application/x-ndjson",
                    headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})


def ollama_error_message(exc) -> str:
    if isinstance(exc, rag_core.ollama.ResponseError):
        detail = str(exc).splitlines()[0][:240]
        return f"Ollama recibió la consulta, pero el modelo devolvió un error: {detail}"
    if "ConnectError" in type(exc).__name__ or "Connection refused" in str(exc):
        return "VEXA no pudo conectarse a Ollama en este equipo. Abre Ollama en el computador servidor y vuelve a intentarlo."
    return f"Falló la generación con Ollama ({type(exc).__name__}). Revisa el registro del servidor."


def chat_profile():
    """(perfil, None) o (None, respuesta de error) según el estado de Ollama."""
    try:
        installed = model_select.instalados_ollama()
    except Exception:
        return None, (jsonify(ok=False, error="Ollama no responde en este equipo. Abre Ollama y vuelve a intentarlo."), 503)
    perfil = model_select.perfil_para(installed)
    if not model_select.modelo_instalado(perfil.modelo, installed):
        return None, (jsonify(ok=False, error=f"No está instalado el modelo de chat {perfil.modelo}. Ejecuta "
                                              f"'ollama pull {perfil.modelo}' y vuelve a intentarlo."), 503)
    return perfil, None
