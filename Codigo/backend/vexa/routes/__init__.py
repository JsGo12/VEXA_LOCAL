"""Registro de blueprints. Cada módulo agrupa las rutas de un área funcional."""
from __future__ import annotations

from flask import Flask


def register_routes(app: Flask) -> None:
    from vexa.routes import access, admin, assistant, audit_log, auth, cases, system

    for module in (auth, system, admin, access, audit_log, cases, assistant):
        app.register_blueprint(module.bp)
    system.install_error_handlers(app)

    from vexa.services.cases import STATUS_LABELS

    @app.context_processor
    def _inject_case_labels():
        return {"STATUS_LABELS": STATUS_LABELS}
