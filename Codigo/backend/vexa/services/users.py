"""Cuentas, roles, equipos y administrador inicial."""
from __future__ import annotations

import secrets
import sqlite3
from pathlib import Path
from typing import Iterable, List, Optional

from werkzeug.security import check_password_hash, generate_password_hash

from vexa.database import connect

MIN_PASSWORD = 10
CREDENTIALS_FILE = "credenciales_admin_inicial.txt"


class UserError(ValueError):
    """Error de validación apto para mostrarse al usuario."""


def ensure_initial_admin(db_path: Path, data_dir: Path, username: str = "admin",
                         password: Optional[str] = None) -> Optional[str]:
    """Crea UN administrador en una instalación sin administradores (atómico ante arranques paralelos).

    La contraseña se genera localmente si no se configuró VEXA_ADMIN_PASSWORD y se escribe una sola
    vez en `credenciales_admin_inicial.txt` (el administrador debe borrarlo). Devuelve el usuario creado.
    """
    db = sqlite3.connect(db_path, timeout=30, isolation_level=None)
    db.row_factory = sqlite3.Row
    try:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT 1 FROM users WHERE role = 'admin' LIMIT 1").fetchone():
            db.execute("ROLLBACK")
            return None
        username = (username or "admin").strip() or "admin"
        if db.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
            db.execute("ROLLBACK")
            raise RuntimeError(f"No se puede crear el administrador: el usuario '{username}' ya existe. "
                               "Configura VEXA_ADMIN_USERNAME con otro nombre.")
        generated = password is None
        if generated:
            password = secrets.token_urlsafe(24)
        user_id = db.execute(
            "INSERT INTO users(name, username, password_hash, role, must_change_password) VALUES (?, ?, ?, 'admin', ?)",
            ("Administrador VEXA", username, generate_password_hash(password), 1 if generated else 0)).lastrowid
        db.execute("INSERT OR IGNORE INTO access_grants(user_id, scope_type, scope_id) VALUES (?, 'firm', NULL)",
                   (user_id,))
        db.execute("COMMIT")
    except Exception:
        if db.in_transaction:
            db.execute("ROLLBACK")
        raise
    finally:
        db.close()
    if generated:
        (Path(data_dir) / CREDENTIALS_FILE).write_text(
            "Credenciales iniciales de VEXA\n"
            f"Usuario: {username}\n"
            f"Contraseña inicial: {password}\n\n"
            "Entrega estos datos al administrador y elimina este archivo.\n",
            encoding="utf-8",
        )
    return username


def authenticate(db_path: Path, username: str, password: str):
    with connect(db_path) as db:
        user = db.execute("SELECT * FROM users WHERE username = ? AND active = 1", (username,)).fetchone()
    if user and check_password_hash(user["password_hash"], password):
        return user
    return None


def create_user(db_path: Path, name: str, username: str, password: str, role: str) -> int:
    name, username = name.strip(), username.strip()
    if not name or not username or len(password) < MIN_PASSWORD:
        raise UserError(f"Completa los campos. La contraseña debe tener al menos {MIN_PASSWORD} caracteres.")
    if len(name) > 100 or len(username) > 60:
        raise UserError("El nombre o el usuario son demasiado largos.")
    try:
        with connect(db_path) as db:
            # La contraseña la define otra persona: se exige cambiarla en el primer inicio de sesión.
            return db.execute("INSERT INTO users(name, username, password_hash, role, must_change_password) "
                              "VALUES (?, ?, ?, ?, 1)",
                              (name, username, generate_password_hash(password), role)).lastrowid
    except sqlite3.IntegrityError as exc:
        raise UserError("Ese nombre de usuario ya existe.") from exc


def change_own_password(db_path: Path, user_id: int, current: str, new: str, confirm: str) -> int:
    """Cambia la contraseña propia verificando la actual. Devuelve la nueva época de sesión."""
    if new != confirm:
        raise UserError("La nueva contraseña y su confirmación no coinciden.")
    if len(new) < MIN_PASSWORD:
        raise UserError(f"La nueva contraseña debe tener al menos {MIN_PASSWORD} caracteres.")
    with connect(db_path) as db:
        row = db.execute("SELECT password_hash FROM users WHERE id = ? AND active = 1", (user_id,)).fetchone()
        if row is None or not check_password_hash(row["password_hash"], current):
            raise UserError("La contraseña actual no es correcta.")
        if check_password_hash(row["password_hash"], new):
            raise UserError("La nueva contraseña debe ser distinta de la actual.")
        db.execute("UPDATE users SET password_hash = ?, must_change_password = 0, session_epoch = session_epoch + 1 "
                   "WHERE id = ?", (generate_password_hash(new), user_id))
        return db.execute("SELECT session_epoch FROM users WHERE id = ?", (user_id,)).fetchone()[0]


def reset_password(db_path: Path, user_id: int, new: str) -> None:
    """Contraseña temporal asignada por un administrador: cierra sus sesiones abiertas y exige cambio."""
    if len(new) < MIN_PASSWORD:
        raise UserError(f"La contraseña temporal debe tener al menos {MIN_PASSWORD} caracteres.")
    with connect(db_path) as db:
        db.execute("UPDATE users SET password_hash = ?, must_change_password = 1, session_epoch = session_epoch + 1 "
                   "WHERE id = ?", (generate_password_hash(new), user_id))


def set_role(db_path: Path, user_id: int, role: str) -> None:
    with connect(db_path) as db:
        db.execute("UPDATE users SET role = ?, session_epoch = session_epoch + 1 WHERE id = ?", (role, user_id))


def set_active(db_path: Path, user_id: int, active: bool) -> None:
    with connect(db_path) as db:
        db.execute("UPDATE users SET active = ?, session_epoch = session_epoch + 1 WHERE id = ?",
                   (1 if active else 0, user_id))


def list_users(db_path: Path):
    with connect(db_path) as db:
        return db.execute("SELECT id, name, username, role, active, created_at FROM users ORDER BY active DESC, name").fetchall()


def assignable_users(db_path: Path):
    with connect(db_path) as db:
        return db.execute("SELECT id, name, username, role FROM users WHERE active = 1 AND role IN "
                          "('lawyer', 'chief_lawyer') ORDER BY name").fetchall()


def _valid_members(db: sqlite3.Connection, member_ids: Iterable[int]) -> List[int]:
    members = list(dict.fromkeys(int(m) for m in member_ids))
    if not members:
        return []
    marks = ",".join("?" for _ in members)
    return [row[0] for row in db.execute(
        f"SELECT id FROM users WHERE role IN ('lawyer', 'chief_lawyer') AND active = 1 AND id IN ({marks})",
        members).fetchall()]


def create_team(db_path: Path, name: str, member_ids: Iterable[int]) -> int:
    name = name.strip()
    member_ids = list(member_ids)
    if not name or not member_ids:
        raise UserError("Indica el nombre del equipo y selecciona al menos un integrante.")
    try:
        with connect(db_path) as db:
            team_id = db.execute("INSERT INTO teams(name) VALUES (?)", (name,)).lastrowid
            db.executemany("INSERT INTO team_members(team_id, user_id) VALUES (?, ?)",
                           [(team_id, m) for m in _valid_members(db, member_ids)])
            return team_id
    except sqlite3.IntegrityError as exc:
        raise UserError("Ya existe un equipo con ese nombre.") from exc


def set_team_members(db_path: Path, team_id: int, member_ids: Iterable[int]) -> List[int]:
    with connect(db_path) as db:
        if db.execute("SELECT 1 FROM teams WHERE id = ?", (team_id,)).fetchone() is None:
            raise UserError("El equipo no existe.")
        members = _valid_members(db, member_ids)
        if not members:
            raise UserError("Un equipo debe tener al menos un integrante.")
        db.execute("DELETE FROM team_members WHERE team_id = ?", (team_id,))
        db.executemany("INSERT INTO team_members(team_id, user_id) VALUES (?, ?)", [(team_id, m) for m in members])
        return members


def list_teams(db_path: Path):
    with connect(db_path) as db:
        teams = db.execute("SELECT id, name FROM teams ORDER BY name").fetchall()
        members = db.execute("SELECT m.team_id, u.id, u.name FROM team_members m JOIN users u ON u.id = m.user_id "
                             "ORDER BY u.name").fetchall()
    by_team = {}
    for row in members:
        by_team.setdefault(row["team_id"], []).append({"id": row["id"], "name": row["name"]})
    return [{"id": t["id"], "name": t["name"], "members": by_team.get(t["id"], [])} for t in teams]
