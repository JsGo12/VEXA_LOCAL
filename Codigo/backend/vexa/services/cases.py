"""Expedientes y documentos: creación, asignación, almacenamiento cifrado y carpeta vigilada."""
from __future__ import annotations

import hashlib
import logging
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from werkzeug.utils import secure_filename

from vexa.database import connect
from vexa.rag import formats
from vexa.security import vault

LOGGER = logging.getLogger(__name__)
ALLOWED_EXTENSIONS = formats.SUPPORTED
ASSIGNABLE_ROLES = ("lawyer", "chief_lawyer")


class CaseError(ValueError):
    """Error de validación apto para mostrarse al usuario."""


def sanitize_filename(name: str) -> str:
    return secure_filename(name or "") or "documento"


def validate_upload(filename: str, content: bytes, max_size: int) -> str:
    safe_name = sanitize_filename(filename)
    if Path(safe_name).suffix.lower() not in ALLOWED_EXTENSIONS:
        raise CaseError("Formato no admitido. Usa PDF, DOCX, XLSX, PPTX, TXT o CSV.")
    if len(content) > max_size:
        raise CaseError(f"Cada archivo debe pesar como máximo {max_size // (1024 * 1024)} MB.")
    if not content:
        raise CaseError("El archivo está vacío.")
    return safe_name


def _assignee_valid(db: sqlite3.Connection, assignment_type: str, assignee_id: int) -> bool:
    if assignment_type == "user":
        row = db.execute("SELECT role FROM users WHERE id = ? AND active = 1", (assignee_id,)).fetchone()
        return row is not None and row["role"] in ASSIGNABLE_ROLES
    return db.execute("SELECT 1 FROM teams WHERE id = ?", (assignee_id,)).fetchone() is not None


def parse_assignment(assignment_type: Optional[str], raw_assignee: str) -> Tuple[str, int]:
    if assignment_type not in {"user", "team"} or not raw_assignee:
        raise CaseError("Selecciona el responsable del caso.")
    try:
        return assignment_type, int(raw_assignee)
    except ValueError as exc:
        raise CaseError("El responsable seleccionado no es válido.") from exc


def parse_due_date(due_at: str) -> str:
    try:
        due_time = datetime.strptime(due_at, "%Y-%m-%dT%H:%M")
    except ValueError as exc:
        raise CaseError("La fecha límite no es válida.") from exc
    if due_time <= datetime.now():
        raise CaseError("La fecha límite debe ser futura.")
    return due_at


def create_case(db_path: Path, upload_dir: Path, *, title: str, summary: str, reference: str,
                due_at: str, assignment_type: str, assignee_id: int, files: List[Tuple[str, bytes]],
                created_by: int) -> int:
    """Crea el caso, su asignación y sus documentos cifrados en una sola transacción."""
    storage_dir = Path(upload_dir) / uuid.uuid4().hex
    storage_dir.mkdir(parents=True, exist_ok=True)
    try:
        with connect(db_path) as db:
            if not _assignee_valid(db, assignment_type, assignee_id):
                raise CaseError("El abogado o equipo seleccionado ya no existe.")
            case_id = db.execute(
                "INSERT INTO cases(title, summary, reference, due_at, created_by) VALUES (?, ?, ?, ?, ?)",
                (title, summary, reference, due_at, created_by)).lastrowid
            column = "user_id" if assignment_type == "user" else "team_id"
            db.execute(f"INSERT INTO case_assignments(case_id, {column}) VALUES (?, ?)", (case_id, assignee_id))
            for original_name, content in files:
                stored = storage_dir / f"{uuid.uuid4().hex}{Path(original_name).suffix.lower()}"
                vault.write_encrypted(stored, content)
                db.execute(
                    "INSERT INTO documents(case_id, original_name, stored_path, sha256, uploaded_by) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (case_id, original_name, str(stored), hashlib.sha256(content).hexdigest(), created_by))
        return case_id
    except Exception:
        for stored in storage_dir.glob("*"):
            stored.unlink(missing_ok=True)
        storage_dir.rmdir()
        raise


def reassign_case(db_path: Path, case_id: int, assignment_type: str, assignee_id: int) -> None:
    with connect(db_path) as db:
        if db.execute("SELECT 1 FROM cases WHERE id = ?", (case_id,)).fetchone() is None:
            raise CaseError("El caso no existe.")
        if not _assignee_valid(db, assignment_type, assignee_id):
            raise CaseError("El abogado o equipo seleccionado no es válido.")
        user_id, team_id = (assignee_id, None) if assignment_type == "user" else (None, assignee_id)
        db.execute("UPDATE case_assignments SET user_id = ?, team_id = ? WHERE case_id = ?",
                   (user_id, team_id, case_id))


def add_document(db_path: Path, upload_dir: Path, case_id: int, name: str, content: bytes, uploaded_by: int) -> int:
    storage_dir = Path(upload_dir) / uuid.uuid4().hex
    storage_dir.mkdir(parents=True, exist_ok=True)
    stored = storage_dir / f"{uuid.uuid4().hex}{Path(name).suffix.lower()}"
    vault.write_encrypted(stored, content)
    with connect(db_path) as db:
        return db.execute(
            "INSERT INTO documents(case_id, original_name, stored_path, sha256, uploaded_by) VALUES (?, ?, ?, ?, ?)",
            (case_id, name, str(stored), hashlib.sha256(content).hexdigest(), uploaded_by)).lastrowid


def ingest_watched_file(db_path: Path, upload_dir: Path, max_size: int, case_id: int, path: Path) -> bool:
    """Agrega un archivo de la carpeta vigilada al caso (cifrado). Devuelve False si se rechaza."""
    with connect(db_path) as db:
        case = db.execute("SELECT created_by FROM cases WHERE id = ?", (case_id,)).fetchone()
    name = sanitize_filename(path.name)
    if not case or Path(name).suffix.lower() not in ALLOWED_EXTENSIONS:
        return False
    try:
        if path.stat().st_size > max_size:
            LOGGER.warning("Archivo vigilado demasiado grande (máximo %s bytes): %s", max_size, name)
            return False
        with path.open("rb") as source:
            content = source.read(max_size + 1)
    except OSError:
        return False
    if not content or len(content) > max_size:
        return False
    add_document(db_path, upload_dir, case_id, name, content, case["created_by"])
    LOGGER.info("Carpeta vigilada: %s agregado al caso %s", name, case_id)
    return True


CASE_LIST_SQL = """
    SELECT c.*, u.name AS assignee_name, t.name AS team_name, a.user_id AS assigned_user_id, a.team_id,
           (SELECT COUNT(*) FROM documents d WHERE d.case_id = c.id) AS document_count
    FROM cases c JOIN case_assignments a ON a.case_id = c.id
    LEFT JOIN users u ON u.id = a.user_id LEFT JOIN teams t ON t.id = a.team_id
"""


def all_cases(db_path: Path):
    with connect(db_path) as db:
        return db.execute(CASE_LIST_SQL + " ORDER BY c.due_at ASC").fetchall()


def cases_by_ids(db_path: Path, case_ids: Iterable[int]):
    ids = [int(i) for i in case_ids]
    if not ids:
        return []
    with connect(db_path) as db:
        marks = ",".join("?" for _ in ids)
        return db.execute(CASE_LIST_SQL + f" WHERE c.id IN ({marks}) ORDER BY c.due_at ASC", ids).fetchall()


def preview_text(document) -> str:
    pages = formats.extraer(document["stored_path"], vault.read_bytes(document["stored_path"]))
    if not pages:
        return ""
    full_text = " ".join(pages[0]["text"].split())
    return full_text[:650] + ("..." if len(full_text) > 650 else "")


# ------------------------------------------------------------------ avance del caso
STATUS_LABELS = {"pendiente": "Pendiente", "en_curso": "En curso", "en_revision": "En revisión", "cerrado": "Cerrado"}
MAX_NOTE = 2000


# Motivos al cerrar un caso. Solo «completado» lleva el avance a 100 %; con los demás se conserva el
# porcentaje real (un caso abandonado al 40 % sigue mostrando 40 %).
CLOSE_REASONS = {
    "completado": "Completado",
    "acuerdo": "Acuerdo entre las partes",
    "desistimiento": "Desistimiento del cliente",
    "abandono": "Abandono",
    "archivado": "Archivado",
    "otro": "Otro motivo",
}


def close_label(status: str, close_reason: str = "") -> str:
    """Texto del estado con su motivo: «Cerrado · Abandono»."""
    label = STATUS_LABELS.get(status, status)
    if status == "cerrado":
        return f"{label} · {CLOSE_REASONS.get(close_reason, 'sin motivo registrado')}"
    return label


def parse_progress(status: str, raw_progress: str, note: str, close_reason: str = "") -> Tuple[str, int, str, str]:
    """Valida estado, avance, nota y motivo de cierre. Devuelve (estado, avance, nota, motivo)."""
    if status not in STATUS_LABELS:
        raise CaseError("Selecciona un estado válido.")
    try:
        progress = int(raw_progress)
    except (TypeError, ValueError) as exc:
        raise CaseError("El avance debe ser un número entre 0 y 100.") from exc
    if not 0 <= progress <= 100:
        raise CaseError("El avance debe estar entre 0 y 100.")
    close_reason = (close_reason or "").strip()
    if status == "cerrado":
        if close_reason not in CLOSE_REASONS:
            raise CaseError("Indica el motivo de cierre del caso (completado, acuerdo, abandono…).")
        if close_reason == "completado":
            progress = 100
    else:
        close_reason = ""                       # al reabrir, el motivo anterior deja de aplicar
    note = (note or "").strip()
    if len(note) > MAX_NOTE:
        raise CaseError(f"La nota puede tener como máximo {MAX_NOTE} caracteres.")
    return status, progress, note, close_reason


def update_progress(db_path: Path, case_id: int, user_id: int, status: str, progress: int, note: str,
                    close_reason: str = "") -> int:
    """Actualiza el estado del caso y registra la actualización (la nota se guarda cifrada)."""
    with connect(db_path) as db:
        if db.execute("SELECT 1 FROM cases WHERE id = ?", (case_id,)).fetchone() is None:
            raise CaseError("El caso no existe.")
        db.execute("UPDATE cases SET status = ?, progress = ?, close_reason = ? WHERE id = ?",
                   (status, progress, close_reason, case_id))
        return db.execute(
            "INSERT INTO case_updates(case_id, user_id, status, progress, note, kind, close_reason) "
            "VALUES (?, ?, ?, ?, ?, 'avance', ?)",
            (case_id, user_id, status, progress, vault.enc_text(note) if note else "", close_reason)).lastrowid


def add_note(db_path: Path, case_id: int, user_id: int, note: str) -> int:
    """Nota del abogado (cómo va, evidencias): no cambia estado ni porcentaje. Se guarda cifrada."""
    note = (note or "").strip()
    if not note:
        raise CaseError("Escribe la nota antes de registrarla.")
    if len(note) > 2000:
        raise CaseError("La nota no puede superar los 2000 caracteres.")
    with connect(db_path) as db:
        case = db.execute("SELECT status, progress FROM cases WHERE id = ?", (case_id,)).fetchone()
        if case is None:
            raise CaseError("El caso no existe.")
        return db.execute(
            "INSERT INTO case_updates(case_id, user_id, status, progress, note, kind) VALUES (?, ?, ?, ?, ?, 'nota')",
            (case_id, user_id, case["status"], case["progress"], vault.enc_text(note))).lastrowid


def set_due_date(db_path: Path, case_id: int, due_at: str) -> str:
    """Cambia la fecha límite (ya validada con parse_due_date). Devuelve la fecha anterior."""
    with connect(db_path) as db:
        row = db.execute("SELECT due_at FROM cases WHERE id = ?", (case_id,)).fetchone()
        if row is None:
            raise CaseError("El caso no existe.")
        db.execute("UPDATE cases SET due_at = ? WHERE id = ?", (due_at, case_id))
    return row["due_at"]


def case_updates(db_path: Path, case_id: int, limit: int = 30) -> List[dict]:
    with connect(db_path) as db:
        rows = db.execute("""SELECT u.id, u.status, u.progress, u.note, u.kind, u.close_reason, u.created_at, us.name AS author
                             FROM case_updates u LEFT JOIN users us ON us.id = u.user_id
                             WHERE u.case_id = ? ORDER BY u.id DESC LIMIT ?""", (case_id, limit)).fetchall()
    return [{**dict(r), "note": vault.dec_text(r["note"]) if r["note"] else "",
             "status_label": close_label(r["status"], r["close_reason"])} for r in rows]


DEADLINE_LABELS = {"vencido": "Vencido", "pronto": "Vence pronto", "al_dia": "Al día", "cerrado": "Cerrado"}


def deadline_state(due_at: str, status: str, now: Optional[datetime] = None, soon_days: int = 7) -> str:
    """Semáforo de un caso: 'vencido' (abierto y pasado), 'pronto' (abierto, < soon_days), 'al_dia' o
    'cerrado' (los casos cerrados ya no corren plazo, se cerraran completos o no)."""
    if status == "cerrado":
        return "cerrado"
    try:
        due = datetime.strptime(due_at, "%Y-%m-%dT%H:%M")
    except (TypeError, ValueError):
        return "al_dia"
    now = now or datetime.now()
    if due < now:
        return "vencido"
    return "pronto" if (due - now).days < soon_days else "al_dia"


def follow_up(db_path: Path, soon_days: int = 7, case_ids: Optional[Iterable[int]] = None) -> dict:
    """Datos del panel de seguimiento: solo metadatos (sin notas ni contenido documental).
    case_ids limita el panel (abogado jefe: solo los casos de su alcance)."""
    now = datetime.now()
    with connect(db_path) as db:
        rows = db.execute(CASE_LIST_SQL.replace(
            "(SELECT COUNT(*) FROM documents d WHERE d.case_id = c.id) AS document_count",
            """(SELECT COUNT(*) FROM documents d WHERE d.case_id = c.id) AS document_count,
               (SELECT MAX(created_at) FROM case_updates cu WHERE cu.case_id = c.id) AS last_update,
               (SELECT MAX(created_at) FROM chat_messages m WHERE m.case_id = c.id) AS last_chat,
               (SELECT MAX(uploaded_at) FROM documents d2 WHERE d2.case_id = c.id) AS last_document""")
            + " ORDER BY c.due_at ASC").fetchall()
    if case_ids is not None:
        keep = set(case_ids)
        rows = [r for r in rows if r["id"] in keep]
    cases, counts = [], {k: 0 for k in STATUS_LABELS}
    for r in rows:
        item = dict(r)
        counts[item["status"]] = counts.get(item["status"], 0) + 1
        # Semáforo del panel: rojo vencido, amarillo pronto, verde el resto (incluye cerrados).
        item["deadline_state"] = deadline_state(item["due_at"], item["status"], now, soon_days)
        item["overdue"] = item["deadline_state"] == "vencido"
        item["due_soon"] = item["deadline_state"] == "pronto"
        item["status_label"] = close_label(item["status"], item.get("close_reason", ""))
        item["last_activity"] = max((v for v in (item["last_update"], item["last_chat"], item["last_document"],
                                                 item["created_at"]) if v), default=None)
        cases.append(item)
    return {
        "cases": cases, "counts": counts,
        "overdue": [c for c in cases if c["overdue"]],
        "due_soon": [c for c in cases if c["due_soon"]],
        "stale": [c for c in cases if c["status"] != "cerrado" and not c["last_update"]],
    }
