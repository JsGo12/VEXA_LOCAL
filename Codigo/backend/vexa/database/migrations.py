"""Esquema y migraciones versionadas de SQLite (PRAGMA user_version).

Reglas:
- El esquema base reproduce exactamente las tablas de la versión anterior (CREATE IF NOT EXISTS),
  así una base existente no cambia al crearlo.
- Cada migración es idempotente y se aplica dentro de una transacción.
- Si la base ya tenía datos y hay migraciones pendientes, antes se crea una copia consistente
  (API de respaldo de SQLite) en `<VEXA_DATA_DIR>/backups/`.
- Ninguna migración elimina usuarios, casos, asignaciones, documentos ni historial.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from vexa.database import store

LOGGER = logging.getLogger(__name__)

BASE_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('admin', 'lawyer')),
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS teams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS team_members (
    team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    PRIMARY KEY(team_id, user_id)
);
CREATE TABLE IF NOT EXISTS cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    reference TEXT NOT NULL DEFAULT '',
    due_at TEXT NOT NULL,
    created_by INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS case_assignments (
    case_id INTEGER PRIMARY KEY REFERENCES cases(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id),
    team_id INTEGER REFERENCES teams(id),
    CHECK ((user_id IS NOT NULL AND team_id IS NULL) OR
           (user_id IS NULL AND team_id IS NOT NULL))
);
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    original_name TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    uploaded_by INTEGER NOT NULL REFERENCES users(id),
    uploaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

USERS_V2 = """
CREATE TABLE users_v2 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('admin', 'chief_lawyer', 'lawyer')),
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""


def _run_script(db: sqlite3.Connection, script: str) -> None:
    """Ejecuta sentencias una a una: `executescript` haría COMMIT y rompería la atomicidad."""
    for statement in script.split(";"):
        if statement.strip():
            db.execute(statement)


def _columns(db: sqlite3.Connection, table: str) -> set:
    return {row[1] for row in db.execute(f"PRAGMA table_info({table})").fetchall()}


def _m1_case_summary(db: sqlite3.Connection) -> None:
    """Versiones antiguas no tenían cases.summary."""
    if "summary" not in _columns(db, "cases"):
        db.execute("ALTER TABLE cases ADD COLUMN summary TEXT NOT NULL DEFAULT ''")


def _m2_chief_lawyer_role(db: sqlite3.Connection) -> None:
    """Amplía el CHECK de users.role para admitir 'chief_lawyer' (SQLite exige reconstruir la tabla).

    Se copian todas las filas con sus mismos id; las claves foráneas de otras tablas siguen
    apuntando a `users` porque la tabla nueva recibe ese nombre. Se valida con foreign_key_check.
    """
    sql = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='users'").fetchone()[0]
    if "chief_lawyer" in sql:
        return
    db.execute("DROP TABLE IF EXISTS users_v2")
    db.execute(USERS_V2)
    db.execute(
        "INSERT INTO users_v2(id, name, username, password_hash, role, active, created_at) "
        "SELECT id, name, username, password_hash, role, active, created_at FROM users"
    )
    before = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    db.execute("DROP TABLE users")
    db.execute("ALTER TABLE users_v2 RENAME TO users")
    after = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if before != after:
        raise RuntimeError("La migración de usuarios no conservó todas las filas.")
    problems = db.execute("PRAGMA foreign_key_check").fetchall()
    if problems:
        raise RuntimeError(f"La migración de usuarios dejó {len(problems)} referencias inválidas.")


def _m3_permissions_audit_assistant(db: sqlite3.Connection) -> None:
    _run_script(db, """
        CREATE TABLE IF NOT EXISTS user_permissions (
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            permission TEXT NOT NULL,
            effect TEXT NOT NULL CHECK(effect IN ('allow', 'deny')),
            granted_by INTEGER REFERENCES users(id),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(user_id, permission)
        );
        CREATE TABLE IF NOT EXISTS access_grants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            scope_type TEXT NOT NULL CHECK(scope_type IN ('firm', 'team', 'case')),
            scope_id INTEGER,
            granted_by INTEGER REFERENCES users(id),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CHECK ((scope_type = 'firm' AND scope_id IS NULL) OR
                   (scope_type <> 'firm' AND scope_id IS NOT NULL))
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_access_grants_unique
            ON access_grants(user_id, scope_type, IFNULL(scope_id, 0));
        CREATE TABLE IF NOT EXISTS document_acl (
            document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            effect TEXT NOT NULL CHECK(effect IN ('allow', 'deny')),
            granted_by INTEGER REFERENCES users(id),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(document_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            user_id INTEGER,
            username TEXT,
            action TEXT NOT NULL,
            resource_type TEXT,
            resource_id TEXT,
            result TEXT NOT NULL CHECK(result IN ('ok', 'denied', 'error')),
            reason TEXT,
            ip TEXT,
            details TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at);
        CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id, created_at);
        CREATE TABLE IF NOT EXISTS assistant_conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_assistant_conv_user ON assistant_conversations(user_id, updated_at);
        CREATE TABLE IF NOT EXISTS assistant_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL REFERENCES assistant_conversations(id) ON DELETE CASCADE,
            role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
            content TEXT NOT NULL,
            metadata TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_assistant_msg_conv ON assistant_messages(conversation_id, id);
        CREATE TABLE IF NOT EXISTS assistant_message_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id INTEGER NOT NULL REFERENCES assistant_messages(id) ON DELETE CASCADE,
            source_type TEXT NOT NULL CHECK(source_type IN ('document', 'case')),
            case_id INTEGER NOT NULL,
            document_id INTEGER,
            label TEXT NOT NULL,
            page_start INTEGER,
            page_end INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_assistant_src_msg ON assistant_message_sources(message_id);
    """)
    if "restricted" not in _columns(db, "documents"):
        db.execute("ALTER TABLE documents ADD COLUMN restricted INTEGER NOT NULL DEFAULT 0")


def _m4_preserve_admin_case_access(db: sqlite3.Connection) -> None:
    """Hasta ahora el administrador veía todos los casos. Esa regla, antes implícita en el código
    por el nombre del rol, pasa a ser un permiso de alcance explícito y revocable ('firm')."""
    db.execute(
        "INSERT OR IGNORE INTO access_grants(user_id, scope_type, scope_id, granted_by) "
        "SELECT id, 'firm', NULL, NULL FROM users WHERE role = 'admin'"
    )


CASE_STATUSES = ("pendiente", "en_curso", "en_revision", "cerrado")


def _m5_case_progress_and_accounts(db: sqlite3.Connection) -> None:
    """Avance de casos (estado, porcentaje, historial de notas) y gestión de contraseñas propias.

    Los casos existentes quedan 'en_curso' con 0 %, que es lo que mostraba la interfaz anterior.
    """
    cols = _columns(db, "cases")
    if "status" not in cols:
        db.execute("ALTER TABLE cases ADD COLUMN status TEXT NOT NULL DEFAULT 'en_curso' "
                   "CHECK(status IN ('pendiente', 'en_curso', 'en_revision', 'cerrado'))")
    if "progress" not in cols:
        db.execute("ALTER TABLE cases ADD COLUMN progress INTEGER NOT NULL DEFAULT 0 "
                   "CHECK(progress BETWEEN 0 AND 100)")
    _run_script(db, """
        CREATE TABLE IF NOT EXISTS case_updates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
            user_id INTEGER REFERENCES users(id),
            status TEXT NOT NULL,
            progress INTEGER NOT NULL,
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_case_updates_case ON case_updates(case_id, id)
    """)
    ucols = _columns(db, "users")
    if "must_change_password" not in ucols:
        db.execute("ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0")
    if "session_epoch" not in ucols:
        db.execute("ALTER TABLE users ADD COLUMN session_epoch INTEGER NOT NULL DEFAULT 0")


MIGRATIONS: List[Tuple[int, str, Callable[[sqlite3.Connection], None]]] = [
    (1, "cases.summary", _m1_case_summary),
    (2, "rol chief_lawyer en users", _m2_chief_lawyer_role),
    (3, "permisos, auditoría y asistente", _m3_permissions_audit_assistant),
    (4, "alcance explícito del administrador", _m4_preserve_admin_case_access),
    (5, "avance de casos y contraseñas propias", _m5_case_progress_and_accounts),
]
LATEST_VERSION = MIGRATIONS[-1][0]


def backup_database(db_path: Path, backups_dir: Path, label: str) -> Path:
    """Copia consistente de la base (incluye lo que esté en el WAL)."""
    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = backups_dir / f"vexa_web-{label}-{stamp}.db"
    source = sqlite3.connect(db_path)
    try:
        dest = sqlite3.connect(target)
        try:
            source.backup(dest)
        finally:
            dest.close()
    finally:
        source.close()
    return target


def current_version(db_path: Path) -> int:
    with sqlite3.connect(db_path) as db:
        return db.execute("PRAGMA user_version").fetchone()[0]


def migrate(db_path: Path, backups_dir: Optional[Path] = None) -> Optional[Path]:
    """Crea/actualiza el esquema. Devuelve la ruta del respaldo previo, si se hizo uno."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    existed = db_path.exists() and db_path.stat().st_size > 0
    db = sqlite3.connect(db_path, timeout=30, isolation_level=None)
    backup = None
    try:
        db.execute("PRAGMA journal_mode = WAL")
        had_tables = db.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='users'"
        ).fetchone()[0] > 0
        version = db.execute("PRAGMA user_version").fetchone()[0]
        pending = [m for m in MIGRATIONS if m[0] > version]
        if pending and existed and had_tables and backups_dir is not None:
            backup = backup_database(db_path, Path(backups_dir), f"antes-de-migrar-v{version}")
            LOGGER.info("Respaldo previo a la migración creado en %s", backup)

        db.executescript(BASE_SCHEMA)
        for number, name, apply in pending:
            db.execute("PRAGMA foreign_keys = OFF")   # requerido para reconstruir tablas
            db.execute("BEGIN IMMEDIATE")
            try:
                apply(db)
                db.execute(f"PRAGMA user_version = {int(number)}")
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                LOGGER.exception("Falló la migración %s (%s); la base quedó en la versión %s",
                                 number, name, number - 1)
                raise
            finally:
                db.execute("PRAGMA foreign_keys = ON")
            LOGGER.info("Migración %s aplicada: %s", number, name)
    finally:
        db.close()
    store.init(db_path)
    return backup
