"""Registro de blueprints. Cada módulo agrupa las rutas de un área funcional."""
from __future__ import annotations

from flask import Flask


def register_routes(app: Flask) -> None:
    from vexa.routes import access, admin, assistant, audit_log, auth, cases, messages, notifications, system

    for module in (auth, system, admin, access, audit_log, cases, assistant, notifications, messages):
        app.register_blueprint(module.bp)
    system.install_error_handlers(app)

    from vexa.services.cases import CLOSE_REASONS, DEADLINE_LABELS, STATUS_LABELS, close_label, deadline_state

    app.add_template_filter(lambda case: deadline_state(case["due_at"], case["status"]), "deadline_state")
    app.add_template_global(DEADLINE_LABELS, "DEADLINE_LABELS")
    app.add_template_global(CLOSE_REASONS, "CLOSE_REASONS")
    app.add_template_filter(lambda case: close_label(case["status"], case["close_reason"] if "close_reason" in case.keys() else ""),
                            "status_label")

    @app.context_processor
    def _inject_case_labels():
        return {"STATUS_LABELS": STATUS_LABELS}

    @app.context_processor
    def _inject_unread_notifications():
        """Número de avisos sin leer para la campana de la barra superior."""
        from flask import g

        from vexa import runtime
        from vexa.services import notifications as notification_service
        user = g.get("user")
        if user is None:
            return {"unread_notifications": 0, "unread_messages": 0}
        try:
            from vexa.services import messages as message_service
            db_path = runtime().settings.db_path
            return {"unread_notifications": notification_service.unread_count(db_path, user["id"]),
                    "unread_messages": message_service.total_unread(db_path, user)}
        except Exception:
            return {"unread_notifications": 0, "unread_messages": 0}
