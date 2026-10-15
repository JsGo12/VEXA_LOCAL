"""Capa SQLite de VEXA: caché de fragmentos/embeddings, historial de chat,
estado de procesamiento y bloqueo de login por intentos fallidos.

Usa la misma base que web_app.py (vexa_web.db). Todas las tablas son nuevas
(CREATE IF NOT EXISTS), así que no toca los datos existentes.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

import vault

SCHEMA = """
CREATE TABLE IF NOT EXISTS doc_chunks (
    doc_sha TEXT NOT NULL,
    chunker TEXT NOT NULL,
    idx INTEGER NOT NULL,
    page INTEGER NOT NULL,
    page_end INTEGER,
    text TEXT NOT NULL,
    PRIMARY KEY (doc_sha, chunker, idx)
);
CREATE TABLE IF NOT EXISTS doc_embeddings (
    doc_sha TEXT NOT NULL,
    chunker TEXT NOT NULL,
    model TEXT NOT NULL,
    idx INTEGER NOT NULL,
    vec BLOB NOT NULL,
    PRIMARY KEY (doc_sha, chunker, model, idx)
);
CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('user','assistant')),
    content TEXT NOT NULL,
    sources TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_chat_case_user ON chat_messages(case_id, user_id, id);
CREATE TABLE IF NOT EXISTS case_summaries (
    case_id INTEGER PRIMARY KEY,
    signature TEXT NOT NULL,
    summary TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS login_attempts (
    username TEXT PRIMARY KEY COLLATE NOCASE,
    failed INTEGER NOT NULL DEFAULT 0,
    locked_until REAL NOT NULL DEFAULT 0
);
"""

MAX_FAILED = 5
LOCK_SECONDS = 5 * 60


def connect(db_path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init(db_path) -> None:
    with connect(db_path) as db:
        db.executescript(SCHEMA)


# ---------------------------------------------------------------- fragmentos
def load_chunks(db_path, doc_sha: str, chunker: str) -> Optional[List[Tuple]]:
    with connect(db_path) as db:
        rows = db.execute(
            "SELECT idx, page, page_end, text FROM doc_chunks "
            "WHERE doc_sha=? AND chunker=? ORDER BY idx", (doc_sha, chunker)).fetchall()
    return [(r["idx"], r["page"], r["page_end"], vault.dec_text(r["text"])) for r in rows] or None


def save_chunks(db_path, doc_sha: str, chunker: str, rows: List[Tuple]) -> None:
    with connect(db_path) as db:
        db.execute("DELETE FROM doc_chunks WHERE doc_sha=? AND chunker=?", (doc_sha, chunker))
        db.execute("DELETE FROM doc_embeddings WHERE doc_sha=? AND chunker=?", (doc_sha, chunker))
        db.executemany(
            "INSERT INTO doc_chunks(doc_sha, chunker, idx, page, page_end, text) VALUES (?,?,?,?,?,?)",
            [(doc_sha, chunker, r[0], r[1], r[2], vault.enc_text(r[3])) for r in rows])


def load_vectors(db_path, doc_sha: str, chunker: str, model: str, expected: int):
    with connect(db_path) as db:
        rows = db.execute(
            "SELECT idx, vec FROM doc_embeddings WHERE doc_sha=? AND chunker=? AND model=? ORDER BY idx",
            (doc_sha, chunker, model)).fetchall()
    if len(rows) != expected:
        return None
    return np.vstack([
        np.frombuffer(vault.decrypt_bytes(r["vec"]), dtype=np.float32)
        for r in rows
    ])


def save_vectors(db_path, doc_sha: str, chunker: str, model: str, matrix: np.ndarray) -> None:
    """Guarda embeddings cifrados; decrypt_bytes conserva compatibilidad con filas antiguas."""
    with connect(db_path) as db:
        db.executemany(
            "INSERT OR REPLACE INTO doc_embeddings(doc_sha, chunker, model, idx, vec) VALUES (?,?,?,?,?)",
            [(doc_sha, chunker, model, i, vault.encrypt_bytes(row.astype(np.float32).tobytes()))
             for i, row in enumerate(matrix)])


# ------------------------------------------------------------------- chat
def add_message(db_path, case_id: int, user_id: int, role: str, content: str, sources=None) -> None:
    with connect(db_path) as db:
        db.execute(
            "INSERT INTO chat_messages(case_id, user_id, role, content, sources) VALUES (?,?,?,?,?)",
            (case_id, user_id, role, vault.enc_text(content), vault.enc_text(" | ".join(sources or []))))


def recent_messages(db_path, case_id: int, user_id: int, limit: int = 6) -> List[dict]:
    with connect(db_path) as db:
        rows = db.execute(
            "SELECT role, content, sources FROM chat_messages WHERE case_id=? AND user_id=? "
            "ORDER BY id DESC LIMIT ?", (case_id, user_id, limit)).fetchall()
    return [{**dict(r), "content": vault.dec_text(r["content"]), "sources": vault.dec_text(r["sources"])}
            for r in reversed(rows)]


def clear_messages(db_path, case_id: int, user_id: int) -> None:
    with connect(db_path) as db:
        db.execute("DELETE FROM chat_messages WHERE case_id=? AND user_id=?", (case_id, user_id))


# ------------------------------------------------------- bloqueo de login
def lock_remaining(db_path, username: str) -> int:
    with connect(db_path) as db:
        row = db.execute("SELECT locked_until FROM login_attempts WHERE username=?", (username,)).fetchone()
    return max(0, int(row["locked_until"] - time.time())) if row else 0


def register_failed_login(db_path, username: str) -> int:
    """Suma un fallo; al llegar a MAX_FAILED bloquea LOCK_SECONDS. Devuelve intentos restantes."""
    with connect(db_path) as db:
        db.execute("INSERT OR IGNORE INTO login_attempts(username) VALUES (?)", (username,))
        row = db.execute("SELECT failed FROM login_attempts WHERE username=?", (username,)).fetchone()
        failed = row["failed"] + 1
        if failed >= MAX_FAILED:
            db.execute("UPDATE login_attempts SET failed=0, locked_until=? WHERE username=?",
                       (time.time() + LOCK_SECONDS, username))
            return 0
        db.execute("UPDATE login_attempts SET failed=? WHERE username=?", (failed, username))
        return MAX_FAILED - failed


def clear_failed_logins(db_path, username: str) -> None:
    with connect(db_path) as db:
        db.execute("DELETE FROM login_attempts WHERE username=?", (username,))


# ----------------------------------------------------------------- resúmenes
def get_summary(db_path, case_id: int):
    with connect(db_path) as db:
        row = db.execute("SELECT signature, summary FROM case_summaries WHERE case_id=?", (case_id,)).fetchone()
    return (row["signature"], vault.dec_text(row["summary"])) if row else None


def save_summary(db_path, case_id: int, signature: str, summary: str) -> None:
    with connect(db_path) as db:
        db.execute("INSERT OR REPLACE INTO case_summaries(case_id, signature, summary) VALUES (?,?,?)",
                   (case_id, signature, vault.enc_text(summary)))
