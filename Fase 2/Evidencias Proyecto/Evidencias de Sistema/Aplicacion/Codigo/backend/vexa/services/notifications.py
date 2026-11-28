"""Notificaciones dentro de la app.

Solo se avisa a personas que pueden ver el caso (se comprueba con la misma política de acceso), y el
texto contiene metadatos del caso (título, estado, fechas), nunca contenido de documentos ni notas.

Eventos:
    asignacion   caso creado o reasignado  -> responsable(s)
    nota         el abogado registró una nota -> jefes a cargo y quien creó el caso
    avance       cambió el estado/porcentaje   -> responsable(s)
    fecha        cambió la fecha límite        -> responsable(s) y jefes a cargo
    documentos   se agregaron documentos       -> responsable(s)
    vence_pronto / vencido   recordatorio automático (una vez por fecha) -> responsable(s) y jefes a cargo
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterable
from datetime import datetime, timedelta
from pathlib import Path

from vexa.database import connect
from vexa.permissions import policy

LOGGER = logging.getLogger(__name__)
DUE_SOON_DAYS = 3
KEEP_READ_DAYS = 60
ICONS = {"mensaje": "✉", "asignacion": "§", "nota": "✎", "avance": "▲", "fecha": "◷", "documentos": "▤",
         "vence_pronto": "⏳", "vencido": "!"}


# ------------------------------------------------------------------------ destinatarios
def assignees(db, case_id: int) -> set[int]:
    """Responsable directo o integrantes activos del equipo asignado."""
    row = db.execute("SELECT user_id, team_id FROM case_assignments WHERE case_id = ?", (case_id,)).fetchone()
    if row is None:
        return set()
    if row["user_id"] is not None:
        return {int(row["user_id"])}
    return {int(r[0]) for r in db.execute(
        "SELECT m.user_id FROM team_members m JOIN users u ON u.id = m.user_id "
        "WHERE m.team_id = ? AND u.active = 1", (row["team_id"],))}


def supervisors(db, case_id: int) -> set[int]:
    """Abogados jefe a cargo de alguno de los responsables del caso."""
    people = assignees(db, case_id)
    if not people:
        return set()
    marks = ",".join("?" for _ in people)
    return {int(r[0]) for r in db.execute(
        f"SELECT DISTINCT s.chief_id FROM chief_lawyers s JOIN users u ON u.id = s.chief_id "
        f"WHERE s.lawyer_id IN ({marks}) AND u.active = 1", list(people))}


def _case_title(db, case_id: int) -> str:
    row = db.execute("SELECT title FROM cases WHERE id = ?", (case_id,)).fetchone()
    return row["title"] if row else f"caso #{case_id}"


# ------------------------------------------------------------------------------ crear
def notify(db_path: Path, user_ids: Iterable[int], kind: str, title: str, message: str = "",
           case_id: int | None = None, exclude: int | None = None, dedupe: str | None = None) -> int:
    """Crea la notificación para cada destinatario que pueda ver el caso. Devuelve cuántas se crearon."""
    created = 0
    try:
        with connect(db_path) as db:
            for uid in sorted(set(user_ids)):
                if exclude is not None and uid == exclude:
                    continue
                user = db.execute("SELECT id, role, active FROM users WHERE id = ?", (uid,)).fetchone()
                if user is None or not user["active"]:
                    continue
                if case_id is not None and not policy.can_view_case(db, user, case_id):
                    continue                        # nunca avisar de casos que esa persona no ve
                cur = db.execute(
                    "INSERT OR IGNORE INTO notifications(user_id, kind, title, message, case_id, dedupe_key) "
                    "VALUES (?, ?, ?, ?, ?, ?)", (uid, kind, title[:200], message[:400], case_id, dedupe))
                created += cur.rowcount
    except Exception:
        LOGGER.exception("No se pudo crear la notificación %s", kind)
    return created


def case_assigned(db_path: Path, case_id: int, actor_id: int, reassigned: bool = False) -> None:
    with connect(db_path) as db:
        title, people = _case_title(db, case_id), assignees(db, case_id)
        team = db.execute("SELECT t.name FROM case_assignments a JOIN teams t ON t.id = a.team_id "
                          "WHERE a.case_id = ?", (case_id,)).fetchone()
    verb = "Te reasignaron" if reassigned else "Te asignaron"
    text = f"{verb} el caso «{title}»" + (f" (equipo {team['name']})" if team else "") + "."
    notify(db_path, people, "asignacion", text, case_id=case_id, exclude=actor_id)


def note_added(db_path: Path, case_id: int, author_id: int, author_name: str) -> None:
    with connect(db_path) as db:
        title = _case_title(db, case_id)
        people = supervisors(db, case_id)
        creator = db.execute("SELECT created_by FROM cases WHERE id = ?", (case_id,)).fetchone()
        if creator and creator["created_by"]:
            people.add(int(creator["created_by"]))
    notify(db_path, people, "nota", f"{author_name} registró una nota en «{title}».", case_id=case_id,
           exclude=author_id)


def progress_updated(db_path: Path, case_id: int, actor_id: int, status_label: str, progress: int) -> None:
    with connect(db_path) as db:
        title, people = _case_title(db, case_id), assignees(db, case_id)
    notify(db_path, people, "avance", f"Avance de «{title}»: {status_label}, {progress} %.", case_id=case_id,
           exclude=actor_id)


def due_date_changed(db_path: Path, case_id: int, actor_id: int, new_due: str) -> None:
    with connect(db_path) as db:
        title = _case_title(db, case_id)
        people = assignees(db, case_id) | supervisors(db, case_id)
    when = datetime.strptime(new_due, "%Y-%m-%dT%H:%M").strftime("%d-%m-%Y %H:%M")
    notify(db_path, people, "fecha", f"Nueva fecha límite para «{title}»: {when}.", case_id=case_id,
           exclude=actor_id)


def documents_added(db_path: Path, case_id: int, actor_id: int, count: int) -> None:
    with connect(db_path) as db:
        title, people = _case_title(db, case_id), assignees(db, case_id)
    notify(db_path, people, "documentos", f"Se agregaron {count} documento(s) a «{title}».", case_id=case_id,
           exclude=actor_id)


def check_deadlines(db_path: Path, now: datetime | None = None) -> int:
    """Recordatorios de vencimiento (una vez por caso y fecha límite). Devuelve cuántos avisos creó."""
    now = now or datetime.now()
    created = 0
    with connect(db_path) as db:
        cases = db.execute("SELECT id, title, due_at FROM cases WHERE status <> 'cerrado'").fetchall()
        plan = []
        for c in cases:
            try:
                due = datetime.strptime(c["due_at"], "%Y-%m-%dT%H:%M")
            except (TypeError, ValueError):
                continue
            when = due.strftime("%d-%m-%Y %H:%M")
            if due < now:
                kind, text = "vencido", f"El caso «{c['title']}» venció el {when}."
            elif due - now <= timedelta(days=DUE_SOON_DAYS):
                kind, text = "vence_pronto", f"El caso «{c['title']}» vence el {when}."
            else:
                continue
            people = assignees(db, c["id"]) | supervisors(db, c["id"])
            plan.append((people, kind, text, c["id"], f"{kind}:{c['id']}:{c['due_at']}"))
    for people, kind, text, case_id, key in plan:
        created += notify(db_path, people, kind, text, case_id=case_id, dedupe=key)
    return created


def start_deadline_checker(db_path: Path, every: float = 30 * 60) -> threading.Thread:
    """Revisa vencimientos al iniciar y luego cada 30 minutos; limpia avisos leídos antiguos."""
    def loop():
        time.sleep(20)
        while True:
            try:
                check_deadlines(db_path)
                purge_read(db_path)
            except Exception:
                LOGGER.exception("Falló la revisión de vencimientos")
            time.sleep(every)

    thread = threading.Thread(target=loop, name="vexa-vencimientos", daemon=True)
    thread.start()
    return thread


# --------------------------------------------------------------------------- leer
def unread_count(db_path: Path, user_id: int) -> int:
    with connect(db_path) as db:
        return db.execute("SELECT COUNT(*) FROM notifications WHERE user_id = ? AND read_at IS NULL",
                          (user_id,)).fetchone()[0]


def list_for(db_path: Path, user_id: int, limit: int = 100) -> list[dict]:
    with connect(db_path) as db:
        rows = db.execute("SELECT * FROM notifications WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                          (user_id, limit)).fetchall()
    return [{**dict(r), "icon": ICONS.get(r["kind"], "•")} for r in rows]


def get_own(db_path: Path, user_id: int, notification_id: int):
    with connect(db_path) as db:
        return db.execute("SELECT * FROM notifications WHERE id = ? AND user_id = ?",
                          (notification_id, user_id)).fetchone()


def mark_read(db_path: Path, user_id: int, notification_id: int | None = None) -> None:
    with connect(db_path) as db:
        if notification_id is None:
            db.execute("UPDATE notifications SET read_at = CURRENT_TIMESTAMP WHERE user_id = ? AND read_at IS NULL",
                       (user_id,))
        else:
            db.execute("UPDATE notifications SET read_at = COALESCE(read_at, CURRENT_TIMESTAMP) "
                       "WHERE id = ? AND user_id = ?", (notification_id, user_id))


def purge_read(db_path: Path, days: int = KEEP_READ_DAYS) -> int:
    with connect(db_path) as db:
        return db.execute("DELETE FROM notifications WHERE read_at IS NOT NULL AND read_at < datetime('now', ?)",
                          (f"-{int(days)} days",)).rowcount
