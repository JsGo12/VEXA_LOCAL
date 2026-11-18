"""Mensajes del equipo por caso: conversación entre quienes pueden ver el caso.

- El texto se guarda cifrado (vault.enc_text), como las notas de avance.
- Los avisos automáticos (user_id NULL, kind 'sistema') cuentan lo que pasó sin revelar contenido:
  por ejemplo «Se agregaron 2 documentos», sin nombres (podría haber documentos restringidos).
- Al llegar un mensaje se avisa con una notificación a los demás participantes, como máximo una
  sin leer por caso y persona (no se llena la campana con cada mensaje).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Set

from vexa.database import connect
from vexa.permissions import policy
from vexa.security import vault
from vexa.services import notifications

LOGGER = logging.getLogger(__name__)
MAX_BODY = 2000

# Mensajes rápidos (se pueden editar antes de enviar).
QUICK_MESSAGES = [
    ("Faltan documentos", "Faltan documentos para avanzar con el caso: "),
    ("Documentos cargados", "Ya cargué los documentos solicitados en el expediente."),
    ("Plazo ampliado", "Se amplió la fecha límite del caso. Nueva fecha: "),
    ("Necesito revisión", "¿Pueden revisar el avance del caso? Quedó pendiente: "),
    ("Reunión", "Propongo coordinar una reunión sobre este caso el "),
]


class MessageError(ValueError):
    """Mensaje vacío o demasiado largo."""


def participants(db, case_id: int) -> Set[int]:
    """Responsables, jefes a cargo, quien creó el caso y quienes ya escribieron en la conversación."""
    people = notifications.assignees(db, case_id) | notifications.supervisors(db, case_id)
    creator = db.execute("SELECT created_by FROM cases WHERE id = ?", (case_id,)).fetchone()
    if creator and creator["created_by"]:
        people.add(int(creator["created_by"]))
    people |= {int(r[0]) for r in db.execute(
        "SELECT DISTINCT user_id FROM case_messages WHERE case_id = ? AND user_id IS NOT NULL", (case_id,))}
    return people


def _notify_new_message(db_path: Path, case_id: int, author_id: int, author_name: str) -> None:
    with connect(db_path) as db:
        title_row = db.execute("SELECT title FROM cases WHERE id = ?", (case_id,)).fetchone()
        title = title_row["title"] if title_row else f"caso #{case_id}"
        people = participants(db, case_id) - {author_id}
        # Una sola notificación de mensajes sin leer por caso y persona.
        pending = {int(r[0]) for r in db.execute(
            "SELECT user_id FROM notifications WHERE case_id = ? AND kind = 'mensaje' AND read_at IS NULL",
            (case_id,))}
    notifications.notify(db_path, people - pending, "mensaje", f"{author_name} escribió en «{title}».",
                         case_id=case_id)


def post(db_path: Path, case_id: int, user, body: str) -> int:
    """Mensaje de una persona (la ruta ya comprobó permiso y alcance)."""
    body = (body or "").strip()
    if not body:
        raise MessageError("Escribe el mensaje antes de enviarlo.")
    if len(body) > MAX_BODY:
        raise MessageError(f"El mensaje puede tener como máximo {MAX_BODY} caracteres.")
    with connect(db_path) as db:
        message_id = db.execute("INSERT INTO case_messages(case_id, user_id, kind, body) VALUES (?, ?, 'mensaje', ?)",
                                (case_id, int(user["id"]), vault.enc_text(body))).lastrowid
        _mark_read(db, case_id, int(user["id"]), message_id)
    _notify_new_message(db_path, case_id, int(user["id"]), user["name"])
    return message_id


def system(db_path: Path, case_id: int, text: str) -> None:
    """Aviso automático en la conversación del caso (no genera notificación: el evento ya la tiene)."""
    try:
        with connect(db_path) as db:
            db.execute("INSERT INTO case_messages(case_id, user_id, kind, body) VALUES (?, NULL, 'sistema', ?)",
                       (case_id, vault.enc_text(text[:400])))
    except Exception:
        LOGGER.exception("No se pudo registrar el aviso automático del caso %s", case_id)


def assignee_label(db_path: Path, case_id: int) -> str:
    """Nombre del responsable actual («Luis Soto» o «el equipo Litigios»)."""
    with connect(db_path) as db:
        row = db.execute("""SELECT u.name AS person, t.name AS team FROM case_assignments a
                            LEFT JOIN users u ON u.id = a.user_id LEFT JOIN teams t ON t.id = a.team_id
                            WHERE a.case_id = ?""", (case_id,)).fetchone()
    if row is None:
        return "nadie"
    return f"el equipo {row['team']}" if row["team"] else (row["person"] or "nadie")


def due_change_text(actor: str, previous: str, new: str) -> str:
    """«Héctor amplió la fecha límite: 01-03-2026 10:00 → 15-03-2026 10:00.»"""
    from datetime import datetime

    def fmt(value):
        try:
            return datetime.strptime(value, "%Y-%m-%dT%H:%M").strftime("%d-%m-%Y %H:%M")
        except (TypeError, ValueError):
            return str(value)
    verb = "amplió" if (previous or "") < new else "adelantó"
    return f"{actor} {verb} la fecha límite: {fmt(previous)} → {fmt(new)}."


def thread(db_path: Path, case_id: int, viewer_id: int, after_id: int = 0, limit: int = 200) -> List[dict]:
    """Mensajes del caso (más antiguos primero), opcionalmente solo los posteriores a after_id."""
    with connect(db_path) as db:
        rows = db.execute("""SELECT * FROM (
                                 SELECT m.id, m.user_id, m.kind, m.body, m.created_at, u.name, u.username, u.role
                                 FROM case_messages m LEFT JOIN users u ON u.id = m.user_id
                                 WHERE m.case_id = ? AND m.id > ? ORDER BY m.id DESC LIMIT ?)
                             ORDER BY id""", (case_id, after_id, limit)).fetchall()
    result = []
    for r in rows:
        try:
            body = vault.dec_text(r["body"])
        except Exception:
            body = "(no se pudo descifrar este mensaje)"
        result.append({"id": r["id"], "kind": r["kind"], "body": body, "created_at": r["created_at"],
                       "author": r["name"] or ("VEXA" if r["kind"] == "sistema" else "Cuenta eliminada"),
                       "username": r["username"], "role": r["role"], "mine": r["user_id"] == viewer_id})
    return result


def _mark_read(db, case_id: int, user_id: int, message_id: int) -> None:
    db.execute("""INSERT INTO case_message_reads(case_id, user_id, last_read_id) VALUES (?, ?, ?)
                  ON CONFLICT(case_id, user_id) DO UPDATE SET last_read_id = MAX(last_read_id, excluded.last_read_id)""",
               (case_id, user_id, message_id))


def mark_read(db_path: Path, case_id: int, user_id: int) -> None:
    """Marca como leída la conversación (y su notificación de mensajes, si la había)."""
    with connect(db_path) as db:
        last = db.execute("SELECT COALESCE(MAX(id), 0) FROM case_messages WHERE case_id = ?", (case_id,)).fetchone()[0]
        _mark_read(db, case_id, user_id, last)
        db.execute("UPDATE notifications SET read_at = CURRENT_TIMESTAMP WHERE user_id = ? AND case_id = ? "
                   "AND kind = 'mensaje' AND read_at IS NULL", (user_id, case_id))


def unread_count(db_path: Path, case_id: int, user_id: int) -> int:
    with connect(db_path) as db:
        return db.execute("""SELECT COUNT(*) FROM case_messages m
                             LEFT JOIN case_message_reads r ON r.case_id = m.case_id AND r.user_id = ?
                             WHERE m.case_id = ? AND m.id > COALESCE(r.last_read_id, 0)
                               AND (m.user_id IS NULL OR m.user_id <> ?)""", (user_id, case_id, user_id)).fetchone()[0]


def inbox(db_path: Path, user) -> List[dict]:
    """Conversaciones de los casos que la persona puede ver, con el último mensaje y los no leídos."""
    with connect(db_path) as db:
        scope = policy.case_scope(db, user) if policy.has_permission(db, user, "cases.message") else {}
        if not scope:
            return []
        marks = ",".join("?" for _ in scope)
        rows = db.execute(f"""
            SELECT c.id AS case_id, c.title, c.reference, m.id AS last_id, m.body, m.kind, m.created_at,
                   u.name AS author,
                   (SELECT COUNT(*) FROM case_messages x
                      LEFT JOIN case_message_reads r ON r.case_id = x.case_id AND r.user_id = ?
                     WHERE x.case_id = c.id AND x.id > COALESCE(r.last_read_id, 0)
                       AND (x.user_id IS NULL OR x.user_id <> ?)) AS unread
            FROM cases c
            JOIN case_messages m ON m.id = (SELECT MAX(id) FROM case_messages WHERE case_id = c.id)
            LEFT JOIN users u ON u.id = m.user_id
            WHERE c.id IN ({marks}) ORDER BY m.id DESC""", (user["id"], user["id"], *scope)).fetchall()
    result = []
    for r in rows:
        try:
            preview = vault.dec_text(r["body"])
        except Exception:
            preview = ""
        result.append({"case_id": r["case_id"], "title": r["title"], "reference": r["reference"],
                       "preview": preview[:140], "author": r["author"] or "VEXA", "kind": r["kind"],
                       "created_at": r["created_at"], "unread": r["unread"]})
    return result


def total_unread(db_path: Path, user) -> int:
    return sum(item["unread"] for item in inbox(db_path, user))
