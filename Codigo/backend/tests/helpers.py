"""Utilidades de prueba: app aislada en una carpeta temporal y datos de ejemplo ficticios."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from werkzeug.security import generate_password_hash

from vexa import create_app
from vexa.config import Settings
from vexa.database import connect
from vexa.rag import hybrid as rag_hybrid
from vexa.rag import model_select
from vexa.security import vault

CSRF = "test-csrf-token"
PASSWORD = "ContrasenaSegura123"


@dataclass
class Web:
    app: object
    settings: Settings

    @property
    def rt(self):
        return self.app.extensions["vexa"]

    @property
    def indexer(self):
        return self.rt.indexer

    @property
    def db_path(self) -> Path:
        return self.settings.db_path

    @property
    def data_dir(self) -> Path:
        return self.settings.data_dir

    model_select = model_select
    rag_hybrid = rag_hybrid

    def connect_db(self):
        return connect(self.db_path)


def make_settings(tmp_path: Path, **overrides) -> Settings:
    data = tmp_path / "data"
    values = dict(data_dir=data, db_path=data / "vexa_web.db", watch_dir=data / "carpeta_vigilada")
    values.update(overrides)
    return Settings(**values)


def _web_app(monkeypatch, tmp_path, disable_background_index=True, **overrides) -> Web:
    """App bajo una carpeta temporal: las pruebas nunca tocan datos del usuario."""
    settings = make_settings(tmp_path, **overrides)
    web = Web(create_app(settings), settings)
    web.app.config["TESTING"] = True
    if disable_background_index:
        monkeypatch.setattr(web.indexer, "schedule", lambda _case_id: None)
    return web


def add_user(web: Web, username: str, role: str = "lawyer", name: str | None = None) -> int:
    with web.connect_db() as db:
        return db.execute("INSERT INTO users(name, username, password_hash, role) VALUES (?, ?, ?, ?)",
                          (name or username.title(), username, generate_password_hash(PASSWORD), role)).lastrowid


def add_case(web: Web, created_by: int, *, user_id=None, team_id=None, title="Caso privado") -> int:
    with web.connect_db() as db:
        case_id = db.execute("INSERT INTO cases(title, summary, reference, due_at, created_by) VALUES (?, '', '', ?, ?)",
                             (title, "2099-01-01T00:00", created_by)).lastrowid
        db.execute("INSERT INTO case_assignments(case_id, user_id, team_id) VALUES (?, ?, ?)",
                   (case_id, user_id, team_id))
    return case_id


def add_document(web: Web, case_id: int, uploaded_by: int, name: str, content: bytes, *, restricted=0) -> int:
    stored = web.settings.upload_dir / f"{case_id}-{uuid.uuid4().hex}{Path(name).suffix}"
    stored.parent.mkdir(parents=True, exist_ok=True)
    vault.write_encrypted(stored, content)
    with web.connect_db() as db:
        return db.execute("INSERT INTO documents(case_id, original_name, stored_path, sha256, uploaded_by, restricted) "
                          "VALUES (?, ?, ?, ?, ?, ?)",
                          (case_id, name, str(stored), "test-hash-" + name, uploaded_by, restricted)).lastrowid


def _seed_case(web: Web, tmp_path=None):
    """Una abogada asignada, un abogado ajeno, un caso y un documento cifrado."""
    assigned_id = add_user(web, "asignada", name="Abogada asignada")
    other_id = add_user(web, "ajeno", name="Abogado ajeno")
    case_id = add_case(web, assigned_id, user_id=assigned_id)
    document_id = add_document(web, case_id, assigned_id, "contrato.txt", b"Texto de prueba del contrato.")
    return assigned_id, other_id, case_id, document_id


def _client_as(web: Web, user_id):
    client = web.app.test_client()
    with client.session_transaction() as session:
        session["user_id"] = user_id
        session["csrf_token"] = CSRF
    return client


def grant(web: Web, user_id: int, scope_type: str, scope_id=None) -> None:
    with web.connect_db() as db:
        db.execute("INSERT INTO access_grants(user_id, scope_type, scope_id) VALUES (?, ?, ?)",
                   (user_id, scope_type, scope_id))


def admin_id(web: Web, pending_password_change: bool = False) -> int:
    """Administrador inicial. Por defecto se simula que ya cambió su contraseña temporal."""
    with web.connect_db() as db:
        uid = db.execute("SELECT id FROM users WHERE role = 'admin' ORDER BY id LIMIT 1").fetchone()[0]
        if not pending_password_change:
            db.execute("UPDATE users SET must_change_password = 0 WHERE id = ?", (uid,))
        return uid
