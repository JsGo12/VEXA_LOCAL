"""Salud del servicio, estado de Ollama y páginas de error (sin trazas internas)."""
from __future__ import annotations

import logging

from flask import Blueprint, Response, jsonify, render_template, request

from vexa.permissions import login_required
from vexa.rag import hybrid as rag_hybrid
from vexa.rag import model_select

bp = Blueprint("system", __name__)
LOGGER = logging.getLogger(__name__)


@bp.get("/health")
def health():
    """Comprobación mínima para que el lanzador de escritorio espere al backend."""
    return jsonify(ok=True, app="vexa")


@bp.get("/api/ollama/status")
@login_required
def ollama_status():
    try:
        installed = model_select.instalados_ollama()
        perfil = model_select.perfil_para(installed)
        model_name = perfil.modelo
        ready = model_select.modelo_instalado(model_name, installed)
        embed = rag_hybrid.EMBED_MODEL
        semantic = any(n == embed or n.startswith(embed + ":") for n in installed)
        extra = (" · búsqueda por significado activa" if semantic else
                 " · solo palabras exactas (falta ollama pull " + embed + ")")
        return jsonify(connected=True, model=model_name, ready=ready,
                       message=(f"Ollama disponible · {model_name}" + extra) if ready else
                       f"Ollama responde, falta descargar {model_name} (ollama pull {model_name})")
    except Exception:
        model_name = model_select.perfil_para(set()).modelo
        return jsonify(connected=False, model=model_name, ready=False,
                       message="Ollama no responde en este equipo (puerto 11434)")


def _wants_json() -> bool:
    return request.path.startswith("/api/") or request.accept_mimetypes.best == "application/json"


def install_error_handlers(app) -> None:
    def render(code: int, message: str):
        if _wants_json():
            return jsonify(ok=False, error=message), code
        try:
            return render_template("error.html", code=str(code), message=message), code
        except Exception:
            # Antes de enrutar (p. ej. Host no confiable) no hay url_for: respuesta mínima sin plantilla.
            return Response(f"{code} · {message}", status=code, mimetype="text/plain")

    @app.errorhandler(400)
    def bad_request(error):
        return render(400, getattr(error, "description", None) or "Solicitud inválida.")

    @app.errorhandler(403)
    def forbidden(_error):
        return render(403, "No tienes acceso a este recurso.")

    @app.errorhandler(404)
    def not_found(_error):
        return render(404, "No encontramos esa página o documento.")

    @app.errorhandler(413)
    def too_large(_error):
        return render(413, "La carga supera el tamaño máximo permitido.")

    @app.errorhandler(500)
    def internal_error(_error):
        LOGGER.error("Error interno en %s", request.path)
        return render(500, "Ocurrió un error interno. Revisa el registro del servidor.")
