"""Acceso a SQLite: conexión común, esquema/migraciones y caché documental (`store`)."""
from __future__ import annotations

import sqlite3
from pathlib import Path


class _ClosingConnection(sqlite3.Connection):
    """`with connect(...) as db:` confirma o revierte la transacción y además cierra la conexión."""

    def __exit__(self, exc_type, exc, tb):
        try:
            return super().__exit__(exc_type, exc, tb)
        finally:
            self.close()


def connect(db_path: Path | str) -> sqlite3.Connection:
    """Conexión con claves foráneas activas, WAL y espera ante bloqueos."""
    connection = sqlite3.connect(db_path, timeout=15, factory=_ClosingConnection)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection
