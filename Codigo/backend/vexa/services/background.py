"""Servicios de fondo: cifrado de archivos antiguos y carpeta vigilada (una carpeta por caso)."""
from __future__ import annotations

import logging
from vexa.database import connect
from vexa.security import vault
from vexa.services import cases as case_service
from vexa.services.watcher import CarpetaVigilada

LOGGER = logging.getLogger(__name__)


def start_background_services(app) -> None:
    rt = app.extensions["vexa"]
    if rt.services_started:
        return
    settings = rt.settings
    try:
        n = vault.encrypt_existing(settings.upload_dir)
        if n:
            LOGGER.info("Se cifraron %s archivos existentes.", n)
    except Exception:
        LOGGER.exception("No se pudieron cifrar los archivos existentes")
    with connect(settings.db_path) as db:
        case_ids = [row["id"] for row in db.execute("SELECT id FROM cases").fetchall()]
    for case_id in case_ids:
        (settings.watch_dir / str(case_id)).mkdir(parents=True, exist_ok=True)

    def ingest(case_id, path):
        ok = case_service.ingest_watched_file(settings.db_path, settings.upload_dir, settings.max_file_size,
                                              case_id, path)
        if ok:
            rt.indexer.schedule(case_id)
        return ok

    CarpetaVigilada(settings.watch_dir, ingest, case_service.ALLOWED_EXTENSIONS).start()
    rt.services_started = True
