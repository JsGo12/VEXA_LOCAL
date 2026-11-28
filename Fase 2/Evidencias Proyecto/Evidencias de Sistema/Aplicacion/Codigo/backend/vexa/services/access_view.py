"""Datos de la vista de Permisos (solo lectura): permisos agrupados y ficha de cada documento.

La ficha de un documento explica quién puede verlo y por qué, aplicando exactamente las mismas reglas
que el control de acceso (permissions.policy), además de metadatos y sus últimas descargas.
"""
from __future__ import annotations

import os
import sqlite3

from vexa.permissions import policy
from vexa.permissions.catalog import PERMISSIONS, ROLE_PERMISSIONS
from vexa.services.audit_view import local_time

PERMISSION_GROUPS = [
    ("Casos", "§", ["cases.view", "cases.manage", "cases.set_deadline", "cases.update_progress", "cases.add_note",
                    "cases.message"]),
    ("Documentos", "▤", ["documents.view", "documents.download", "documents.upload"]),
    ("Gestión", "◉", ["users.manage", "teams.manage", "permissions.manage", "audit.view"]),
    ("Asistente IA", "✦", ["assistant.use", "assistant.case_access", "assistant.team_access", "assistant.firm_access"]),
]
VIA_LABELS = {
    "assigned": "Caso asignado a su cuenta",
    "team": "Integrante del equipo asignado",
    "grant_case": "Concesión de este caso",
    "grant_team": "Concesión del equipo asignado",
    "firm": "Alcance de toda la firma",
    "supervised": "Abogado jefe a cargo del responsable",
}


def permission_groups(db: sqlite3.Connection, user) -> list[dict]:
    """Permisos por grupo con su origen: rol, ajuste manual o no incluido."""
    role_perms = ROLE_PERMISSIONS.get(user["role"], frozenset())
    overrides = policy.permission_overrides(db, int(user["id"]))
    effective = policy.effective_permissions(db, user)
    listed = {key for _, _, keys in PERMISSION_GROUPS for key in keys}
    groups = PERMISSION_GROUPS + ([("Otros", "·", [k for k in PERMISSIONS if k not in listed])]
                                 if any(k not in listed for k in PERMISSIONS) else [])
    result = []
    for label, icon, keys in groups:
        rows = []
        for key in keys:
            override = overrides.get(key)
            if override == "deny":
                source = "Denegado manualmente"
            elif override == "allow":
                source = "Concedido manualmente" if key not in role_perms else "Concedido (también por rol)"
            elif key in role_perms:
                source = "Incluido en el rol"
            else:
                source = "No incluido en el rol"
            rows.append({"key": key, "label": PERMISSIONS[key], "override": override,
                         "effective": key in effective, "source": source})
        result.append({"label": label, "icon": icon, "rows": rows,
                       "granted": sum(r["effective"] for r in rows)})
    return result


def manageable_people(db: sqlite3.Connection, actor) -> list[sqlite3.Row]:
    """Cuentas que el actor puede revisar aquí: todas para el administrador, sus abogados para el jefe."""
    if actor["role"] == "admin":
        return db.execute("SELECT id, name, username, role, active FROM users ORDER BY active DESC, name").fetchall()
    return db.execute("""SELECT u.id, u.name, u.username, u.role, u.active FROM users u
                         JOIN chief_lawyers s ON s.lawyer_id = u.id WHERE s.chief_id = ?
                         ORDER BY u.active DESC, u.name""", (int(actor["id"]),)).fetchall()


def _size(path: str) -> str | None:
    try:
        size = os.path.getsize(path)
    except OSError:
        return None
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return None


def document_cards(db: sqlite3.Connection, case_id: int, people: list[sqlite3.Row]) -> list[dict]:
    """Ficha de cada documento del caso: metadatos, reglas, quién lo ve (y por qué) y últimas descargas."""
    docs = db.execute("""SELECT d.*, u.name AS uploader FROM documents d LEFT JOIN users u ON u.id = d.uploaded_by
                         WHERE d.case_id = ? ORDER BY d.id""", (case_id,)).fetchall()
    rules: dict[int, list[dict]] = {}
    for row in db.execute("""SELECT a.document_id, a.effect, a.user_id, u.name, u.username FROM document_acl a
                             JOIN users u ON u.id = a.user_id JOIN documents d ON d.id = a.document_id
                             WHERE d.case_id = ? ORDER BY u.name""", (case_id,)):
        rules.setdefault(row["document_id"], []).append(dict(row))
    # Alcance de cada persona listada sobre este caso (una sola consulta por persona).
    reach = {}
    for person in people:
        if not person["active"]:
            continue
        perms = policy.effective_permissions(db, person)
        vias = policy.case_scope(db, person).get(int(case_id), set())
        reach[person["id"]] = (person, perms, vias)
    cards = []
    for doc in docs:
        doc_rules = {r["user_id"]: r["effect"] for r in rules.get(doc["id"], [])}
        can_see, blocked = [], []
        for person, perms, vias in reach.values():
            if not vias:
                continue
            base = {"name": person["name"], "username": person["username"], "role": person["role"]}
            reasons = [VIA_LABELS.get(v, v) for v in sorted(vias)]
            effect = doc_rules.get(person["id"])
            if "documents.view" not in perms:
                blocked.append({**base, "why": "No tiene el permiso de ver documentos"})
            elif effect == "deny":
                blocked.append({**base, "why": "Bloqueado por una regla de este documento"})
            elif doc["restricted"] and effect != "allow":
                blocked.append({**base, "why": "Documento restringido y sin excepción"})
            else:
                why = "Excepción permitida en este documento" if doc["restricted"] else " · ".join(reasons)
                can_see.append({**base, "why": why, "download": "documents.download" in perms})
        downloads = [{"who": r["username"] or "—", "when": local_time(r["created_at"])}
                     for r in db.execute("""SELECT username, created_at FROM audit_log
                                            WHERE action = 'documents.download' AND result = 'ok'
                                              AND resource_type = 'document' AND resource_id = ?
                                            ORDER BY id DESC LIMIT 5""", (str(doc["id"]),))]
        name = doc["original_name"]
        cards.append({
            "id": doc["id"], "name": name, "ext": name.rsplit(".", 1)[-1].upper() if "." in name else "DOC",
            "restricted": bool(doc["restricted"]), "uploader": doc["uploader"] or "—",
            "uploaded_at": local_time(doc["uploaded_at"]), "size": _size(doc["stored_path"]),
            "available": os.path.isfile(doc["stored_path"]), "sha": (doc["sha256"] or "")[:12],
            "rules": rules.get(doc["id"], []), "can_see": can_see, "blocked": blocked, "downloads": downloads,
        })
    return cards
