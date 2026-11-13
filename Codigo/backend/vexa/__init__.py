"""VEXA Local: backend Flask para expedientes jurídicos con RAG local (Ollama).

`create_app()` es la única forma de construir la aplicación: valida la configuración, migra la base,
crea el administrador inicial y registra las rutas. El servidor WSGI (Waitress) vive en `vexa.server`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Tuple

from flask import Flask, current_app

from vexa.config import RESOURCE_DIR, Settings, load_settings
from vexa.database import migrations
from vexa.rag import core as rag_core
from vexa.rag import formats as rag_formats
from vexa.rag import hybrid as rag_hybrid
from vexa.rag import model_select
from vexa.security import network, session_secret, vault
from vexa.services import users as user_service
from vexa.services.assistant import FirmAssistant
from vexa.services.indexing import CaseIndexer

LOGGER = logging.getLogger("vexa")


@dataclass
class Runtime:
    settings: Settings
    indexer: CaseIndexer
    assistant: FirmAssistant
    migration_backup: Optional[Path] = None
    services_started: bool = False


def runtime() -> Runtime:
    return current_app.extensions["vexa"]


def configure_logging(level: str) -> None:
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    root.setLevel(level)


def apply_engine_settings(settings: Settings) -> None:
    """Configura el vault y el motor RAG (Ollama local, modelos, OCR) desde la configuración central."""
    vault.configure(settings.data_dir)
    rag_core.configurar(settings.ollama_host, settings.ollama_keep_alive)
    rag_hybrid.configurar(settings.embed_model)
    model_select.configurar(settings.chat_model)
    rag_formats.configurar(settings.tesseract_cmd)


def create_app(settings: Optional[Settings] = None, *,
               listeners: Optional[Iterable[Tuple[str, int]]] = None,
               start_services: bool = False) -> Flask:
    settings = settings or load_settings()
    configure_logging(settings.log_level)

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    apply_engine_settings(settings)

    backup = migrations.migrate(settings.db_path, settings.backups_dir)
    user_service.ensure_initial_admin(settings.db_path, settings.data_dir,
                                      settings.admin_username, settings.admin_password)

    app = Flask(__name__, template_folder=str(RESOURCE_DIR / "templates"),
                static_folder=str(RESOURCE_DIR / "static"))
    if listeners is None:
        listeners = [(settings.host, settings.port)]
        if settings.tailscale_enabled and settings.tailscale_bind_address:
            listeners.append((settings.tailscale_bind_address, settings.tailscale_port or settings.port))
    app.config.update(
        SECRET_KEY=session_secret.load_session_secret(settings.data_dir, settings.secret_key),
        MAX_CONTENT_LENGTH=100 * 1024 * 1024,
        SESSION_COOKIE_NAME="vexa_session",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=settings.session_cookie_secure,
        PERMANENT_SESSION_LIFETIME=60 * 60 * 8,
        TRUSTED_HOSTS=network.trusted_hosts(settings, listeners),
        PROPAGATE_EXCEPTIONS=False,
        VEXA_DB_PATH=settings.db_path,
    )
    indexer = CaseIndexer(settings.db_path)
    app.extensions["vexa"] = Runtime(settings=settings, indexer=indexer,
                                     assistant=FirmAssistant(settings.db_path, indexer), migration_backup=backup)

    from vexa import permissions
    from vexa.routes import register_routes
    from vexa.security import http

    http.install(app)
    permissions.install(app)
    register_routes(app)
    app.wsgi_app = network.RemoteAddressFilter(app.wsgi_app, allow_tailscale=settings.tailscale_enabled)

    if start_services:
        from vexa.services.background import start_background_services
        start_background_services(app)
    return app
