"""Cuentas, roles, equipos y administrador inicial."""
from __future__ import annotations

import secrets
import sqlite3
from pathlib import Path
from typing import Dict, Iterable, List, Optional

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


def update_own_name(db_path: Path, user_id: int, name: str) -> str:
    """Nombre visible de la cuenta propia (el usuario y el rol no se cambian aquí)."""
    name = " ".join((name or "").split())
    if not name:
        raise UserError("Escribe tu nombre.")
    if len(name) > 100:
        raise UserError("El nombre es demasiado largo (máximo 100 caracteres).")
    with connect(db_path) as db:
        db.execute("UPDATE users SET name = ? WHERE id = ?", (name, user_id))
    return name


def profile_details(db_path: Path, user_id: int) -> dict:
    """Datos de la cuenta para «Mi perfil»: fecha de alta, relaciones jefe-abogado y actividad propia."""
    with connect(db_path) as db:
        created = db.execute("SELECT created_at FROM users WHERE id = ?", (user_id,)).fetchone()
        chiefs = [r["name"] for r in db.execute(
            """SELECT u.name FROM chief_lawyers s JOIN users u ON u.id = s.chief_id
               WHERE s.lawyer_id = ? AND u.active = 1 ORDER BY u.name""", (user_id,))]
        lawyers = [dict(r) for r in db.execute(
            """SELECT u.id, u.name, u.username FROM chief_lawyers s JOIN users u ON u.id = s.lawyer_id
               WHERE s.chief_id = ? AND u.active = 1 ORDER BY u.name""", (user_id,))]
        notes = db.execute("SELECT COUNT(*) FROM case_updates WHERE user_id = ?", (user_id,)).fetchone()[0]
        questions = db.execute("SELECT COUNT(*) FROM chat_messages WHERE user_id = ? AND role = 'user'",
                               (user_id,)).fetchone()[0]
    return {"created_at": created["created_at"] if created else None, "chiefs": chiefs,
            "lawyers": lawyers, "updates_count": notes, "questions_count": questions}


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
        # Las relaciones jefe-abogado solo valen mientras los roles coinciden.
        if role != "chief_lawyer":
            db.execute("DELETE FROM chief_lawyers WHERE chief_id = ?", (user_id,))
        if role != "lawyer":
            db.execute("DELETE FROM chief_lawyers WHERE lawyer_id = ?", (user_id,))


def set_active(db_path: Path, user_id: int, active: bool) -> None:
    with connect(db_path) as db:
        db.execute("UPDATE users SET active = ?, session_epoch = session_epoch + 1 WHERE id = ?",
                   (1 if active else 0, user_id))


def list_users(db_path: Path, supervised_by: Optional[int] = None):
    """Todas las cuentas o, para un abogado jefe, solo los abogados a su cargo."""
    with connect(db_path) as db:
        if supervised_by is None:
            return db.execute("SELECT id, name, username, role, active, created_at FROM users "
                              "ORDER BY active DESC, name").fetchall()
        return db.execute("""SELECT u.id, u.name, u.username, u.role, u.active, u.created_at FROM users u
                             JOIN chief_lawyers s ON s.lawyer_id = u.id WHERE s.chief_id = ?
                             ORDER BY u.active DESC, u.name""", (supervised_by,)).fetchall()


# ------------------------------------------------------- abogados a cargo de un jefe
def add_supervision(db_path: Path, chief_id: int, lawyer_id: int) -> None:
    with connect(db_path) as db:
        db.execute("INSERT OR IGNORE INTO chief_lawyers(chief_id, lawyer_id) VALUES (?, ?)", (chief_id, lawyer_id))


def set_supervised_lawyers(db_path: Path, chief_id: int, lawyer_ids: Iterable[int]) -> List[int]:
    """Reemplaza los abogados a cargo del jefe (ids ya validados por policy.check_supervision)."""
    lawyer_ids = list(lawyer_ids)
    with connect(db_path) as db:
        db.execute("DELETE FROM chief_lawyers WHERE chief_id = ?", (chief_id,))
        db.executemany("INSERT INTO chief_lawyers(chief_id, lawyer_id) VALUES (?, ?)",
                       [(chief_id, lawyer_id) for lawyer_id in lawyer_ids])
    return lawyer_ids


def supervision_map(db_path: Path) -> Dict[int, List[int]]:
    """{id del jefe: [ids de sus abogados]} para el panel del administrador."""
    with connect(db_path) as db:
        rows = db.execute("SELECT chief_id, lawyer_id FROM chief_lawyers ORDER BY chief_id").fetchall()
    result: Dict[int, List[int]] = {}
    for row in rows:
        result.setdefault(int(row["chief_id"]), []).append(int(row["lawyer_id"]))
    return result


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


def list_teams(db_path: Path, only_ids: Optional[Iterable[int]] = None):
    """Equipos con sus integrantes; only_ids limita la lista (equipos que un jefe puede manejar)."""
    with connect(db_path) as db:
        teams = db.execute("SELECT id, name FROM teams ORDER BY name").fetchall()
        members = db.execute("SELECT m.team_id, u.id, u.name FROM team_members m JOIN users u ON u.id = m.user_id "
                             "ORDER BY u.name").fetchall()
    if only_ids is not None:
        keep = set(only_ids)
        teams = [t for t in teams if t["id"] in keep]
    by_team = {}
    for row in members:
        by_team.setdefault(row["team_id"], []).append({"id": row["id"], "name": row["name"]})
    return [{"id": t["id"], "name": t["name"], "members": by_team.get(t["id"], [])} for t in teams]
