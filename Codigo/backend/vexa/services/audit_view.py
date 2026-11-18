"""Presentación del registro de auditoría en lenguaje claro (solo lectura; no cambia lo que se guarda).

Cada evento se traduce a una etiqueta corta y una frase («Abrió el expediente «Despido injustificado».»).
Los títulos de casos y nombres de documentos solo se muestran si quien consulta tiene ese caso en su
alcance; si no, se muestra «caso #N», igual que antes, para no filtrar información por la auditoría.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Dict, Iterable, List, Optional, Set

from vexa.database import connect
from vexa.permissions.catalog import PERMISSIONS, ROLES

# Etiqueta corta de cada acción (para la columna y el filtro).
ACTION_LABELS = {
    "auth.login": "Inicio de sesión",
    "auth.logout": "Cierre de sesión",
    "auth.password_change": "Cambio de contraseña",
    "users.create": "Cuenta creada",
    "users.role_change": "Cambio de rol",
    "users.activate": "Cuenta activada",
    "users.deactivate": "Cuenta desactivada",
    "users.active_change": "Activar o desactivar cuenta",
    "users.password_reset": "Contraseña temporal",
    "users.profile_update": "Perfil actualizado",
    "users.supervision_change": "Abogados a cargo",
    "teams.create": "Equipo creado",
    "teams.members_change": "Integrantes del equipo",
    "cases.create": "Caso creado",
    "cases.open": "Expediente abierto",
    "cases.assignment_change": "Reasignación de caso",
    "cases.progress_update": "Avance actualizado",
    "cases.note_add": "Nota del abogado",
    "cases.due_date_change": "Cambio de fecha límite",
    "cases.download": "Expediente descargado",
    "documents.upload": "Documentos agregados",
    "documents.download": "Documento descargado",
    "documents.restriction": "Restricción de documento",
    "documents.acl": "Acceso a documento",
    "permissions.override": "Ajuste de permiso",
    "permissions.grant": "Alcance concedido",
    "permissions.revoke": "Alcance revocado",
    "assistant.conversation_create": "Conversación creada",
    "assistant.conversation_delete": "Conversación eliminada",
    "assistant.conversation": "Conversación del asistente",
    "assistant.query": "Consulta al asistente",
    "access.denied": "Acceso denegado",
    "backups.create": "Respaldo manual",
    "messages.send": "Mensaje del equipo",
    "exports.follow_up": "Exportación de seguimiento",
    "exports.audit": "Exportación de auditoría",
}
RESULT_LABELS = {"ok": "Correcto", "denied": "Denegado", "error": "Error"}
STATUS = {"pendiente": "Pendiente", "en_curso": "En curso", "en_revision": "En revisión", "cerrado": "Cerrado"}
CLOSE = {"completado": "completado", "acuerdo": "acuerdo entre las partes",
         "desistimiento": "desistimiento del cliente", "abandono": "abandono", "archivado": "archivado",
         "otro": "otro motivo"}
EFFECT = {"allow": "permitido", "deny": "denegado", "clear": "sin ajuste (vuelve al rol)"}
SCOPE = {"firm": "toda la firma", "team": "un equipo", "case": "un caso"}


def action_label(action: str) -> str:
    return ACTION_LABELS.get(action, action.replace(".", " · ").replace("_", " ").capitalize())


def local_time(value: Optional[str]) -> str:
    """'2026-11-14T01:15:51.123Z' (UTC) -> '13-11-2026 22:15' en la hora del servidor."""
    if not value:
        return ""
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        return moment.astimezone().strftime("%d-%m-%Y %H:%M:%S")
    except ValueError:
        return value.replace("T", " ")[:19]


def _date(value: Any) -> str:
    try:
        return datetime.strptime(str(value), "%Y-%m-%dT%H:%M").strftime("%d-%m-%Y %H:%M")
    except ValueError:
        return str(value)


class _Names:
    """Nombres legibles cargados una sola vez por página."""

    def __init__(self, db_path, visible_cases: Optional[Set[int]]):
        with connect(db_path) as db:
            self.users = {r["id"]: r["name"] for r in db.execute("SELECT id, name FROM users")}
            self.teams = {r["id"]: r["name"] for r in db.execute("SELECT id, name FROM teams")}
            self.cases = {r["id"]: r["title"] for r in db.execute("SELECT id, title FROM cases")}
            self.docs = {r["id"]: (r["original_name"], r["case_id"])
                         for r in db.execute("SELECT id, original_name, case_id FROM documents")}
        self.visible = visible_cases            # None = ve todos (administrador con alcance de firma)

    def _can_see(self, case_id) -> bool:
        return self.visible is None or (case_id is not None and int(case_id) in self.visible)

    def case(self, case_id) -> str:
        try:
            cid = int(case_id)
        except (TypeError, ValueError):
            return "un caso"
        if cid in self.cases and self._can_see(cid):
            return f"«{self.cases[cid]}»"
        return f"el caso #{cid}"

    def doc(self, doc_id) -> str:
        try:
            did = int(doc_id)
        except (TypeError, ValueError):
            return "un documento"
        name, case_id = self.docs.get(did, (None, None))
        if name and self._can_see(case_id):
            return f"«{name}»"
        return f"el documento #{did}"

    def user(self, user_id) -> str:
        try:
            return self.users.get(int(user_id), f"la cuenta #{user_id}")
        except (TypeError, ValueError):
            return "una cuenta"

    def team(self, team_id) -> str:
        try:
            return f"«{self.teams[int(team_id)]}»"
        except (KeyError, TypeError, ValueError):
            return f"el equipo #{team_id}"

    def people(self, ids: Iterable) -> str:
        names = [self.user(i) for i in (ids or [])]
        return ", ".join(names) if names else "nadie"

    def assignee(self, kind, assignee_id) -> str:
        return f"el equipo {self.team(assignee_id)}" if kind == "team" else self.user(assignee_id)

    def scope(self, kind, scope_id) -> str:
        if kind == "firm":
            return "toda la firma"
        if kind == "team":
            return f"el equipo {self.team(scope_id)}"
        if kind == "case":
            return f"el caso {self.case(scope_id)}"
        return SCOPE.get(kind, "un alcance")


def _sentence(row, d: Dict[str, Any], n: _Names) -> str:
    """Frase en pasado que explica qué se hizo."""
    a, rid = row["action"], row["resource_id"]
    ok = row["result"] == "ok"
    rtype = row["resource_type"]
    if a == "auth.login":
        return "Inició sesión en VEXA." if ok else "Intentó iniciar sesión sin éxito."
    if a == "auth.logout":
        return "Cerró su sesión."
    if a == "auth.password_change":
        return "Cambió su contraseña." if ok else "Intentó cambiar su contraseña sin éxito."
    if a == "users.create":
        rol = ROLES.get(d.get("rol"), d.get("rol", ""))
        return f"Creó la cuenta de {n.user(rid)} con rol {rol}." if ok else f"Intentó crear una cuenta con rol {rol}."
    if a == "users.role_change":
        if ok:
            return (f"Cambió el rol de {n.user(rid)} de {ROLES.get(d.get('antes'), d.get('antes'))} "
                    f"a {ROLES.get(d.get('despues'), d.get('despues'))}.")
        return f"Intentó cambiar el rol de {n.user(rid)}."
    if a == "users.activate":
        return f"Activó la cuenta de {n.user(rid)}."
    if a == "users.deactivate":
        return f"Desactivó la cuenta de {n.user(rid)}."
    if a == "users.active_change":
        return f"Intentó activar o desactivar la cuenta de {n.user(rid)}."
    if a == "users.password_reset":
        return (f"Asignó una contraseña temporal a {n.user(rid)}." if ok
                else f"Intentó asignar una contraseña temporal a {n.user(rid)}.")
    if a == "users.profile_update":
        return "Actualizó su nombre visible."
    if a == "users.supervision_change":
        if ok:
            return f"Dejó a cargo de {n.user(rid)} a: {n.people(d.get('abogados'))}."
        return f"Intentó cambiar los abogados a cargo de {n.user(rid)}."
    if a == "teams.create":
        return f"Creó el equipo {n.team(rid)}." if ok else "Intentó crear un equipo."
    if a == "teams.members_change":
        if ok:
            return f"Cambió los integrantes del equipo {n.team(rid)}: {n.people(d.get('integrantes'))}."
        return f"Intentó cambiar los integrantes del equipo {n.team(rid)}."
    if a == "cases.create":
        if ok:
            docs = d.get("documentos")
            extra = f" con {docs} documento(s)" if docs is not None else ""
            return (f"Creó el caso {n.case(rid)} y lo asignó a "
                    f"{n.assignee(d.get('asignacion'), d.get('responsable'))}{extra}.")
        return "Intentó crear un caso."
    if a == "cases.open":
        return f"Abrió el expediente {n.case(rid)}."
    if a == "cases.assignment_change":
        if ok:
            return f"Reasignó el caso {n.case(rid)} a {n.assignee(d.get('asignacion'), d.get('responsable'))}."
        return f"Intentó reasignar el caso {n.case(rid)}."
    if a == "cases.progress_update":
        note = " y dejó una nota" if d.get("con_nota") else ""
        reason = f" ({CLOSE.get(d.get('motivo'), d.get('motivo'))})" if d.get("motivo") else ""
        return (f"Actualizó el avance de {n.case(rid)}: {STATUS.get(d.get('estado'), d.get('estado'))}{reason}, "
                f"{d.get('avance')} %{note}.")
    if a == "cases.note_add":
        return f"Registró una nota de avance en {n.case(rid)}."
    if a == "cases.due_date_change":
        if ok:
            return (f"Cambió la fecha límite de {n.case(rid)} del {_date(d.get('anterior'))} "
                    f"al {_date(d.get('nueva'))}.")
        return f"Intentó cambiar la fecha límite de {n.case(rid)}."
    if a == "cases.download":
        if ok:
            return f"Descargó el expediente completo de {n.case(rid)} ({d.get('documentos', 0)} documento(s))."
        return f"Intentó descargar el expediente de {n.case(rid)}."
    if a == "documents.upload":
        count = len(d.get("documentos") or [])
        restricted = ", marcados como restringidos" if d.get("restringidos") else ""
        return f"Agregó {count} documento(s) a {n.case(rid)}{restricted}."
    if a == "documents.download":
        where = f" del caso {n.case(d.get('caso'))}" if d.get("caso") is not None else ""
        return f"Descargó el documento {n.doc(rid)}{where}." if ok else f"No pudo descargar el documento {n.doc(rid)}."
    if a == "documents.restriction":
        if not ok:
            return f"Intentó cambiar la restricción del documento {n.doc(rid)}."
        return (f"Marcó el documento {n.doc(rid)} como restringido." if d.get("restringido")
                else f"Quitó la restricción del documento {n.doc(rid)}.")
    if a == "documents.acl":
        if not ok:
            return f"Intentó cambiar quién puede ver el documento {n.doc(rid)}."
        return (f"Dejó el acceso de {n.user(d.get('usuario'))} al documento {n.doc(rid)} como "
                f"{EFFECT.get(d.get('efecto'), d.get('efecto'))}.")
    if a == "permissions.override":
        perm = PERMISSIONS.get(d.get("permiso"), d.get("permiso"))
        what = f"«{perm}» de {n.user(rid)}"
        return (f"Dejó el permiso {what} como {EFFECT.get(d.get('efecto'), d.get('efecto'))}." if ok
                else f"Intentó cambiar el permiso {what}.")
    if a == "permissions.grant":
        target = n.scope(d.get("alcance"), d.get("id"))
        return f"Concedió a {n.user(rid)} acceso a {target}." if ok else f"Intentó conceder a {n.user(rid)} acceso a {target}."
    if a == "permissions.revoke":
        if rtype == "grant":
            return "Intentó revocar un alcance."
        return f"Revocó a {n.user(rid)} el acceso a {n.scope(d.get('alcance'), d.get('id'))}."
    if a == "assistant.conversation_create":
        return "Inició una conversación con el asistente transversal."
    if a == "assistant.conversation_delete":
        return "Eliminó una conversación del asistente transversal."
    if a == "assistant.query":
        if ok:
            return (f"Consultó al asistente transversal sobre {d.get('expedientes', 0)} expediente(s) "
                    f"y {d.get('documentos', 0)} documento(s) autorizados.")
        return "Intentó consultar al asistente transversal sin expedientes autorizados."
    if a == "backups.create":
        if ok:
            return f"Creó un respaldo manual ({d.get('archivo', 'archivo')})."
        return "Intentó crear un respaldo manual."
    if a == "messages.send":
        return f"Escribió un mensaje al equipo en {n.case(rid)}."
    if a == "exports.follow_up":
        return f"Exportó el panel de seguimiento a Excel ({d.get('casos', 0)} caso(s))."
    if a == "exports.audit":
        return f"Exportó el registro de auditoría a Excel ({d.get('eventos', 0)} evento(s))."
    if a == "access.denied":
        perm = PERMISSIONS.get(d.get("intento"))
        target = ""
        if rtype == "case":
            target = f" sobre {n.case(rid)}"
        elif rtype == "document":
            target = f" sobre el documento {n.doc(rid)}"
        what = f"«{perm[0].lower() + perm[1:]}»" if perm else "una acción"
        return f"Intentó {what}{target} sin autorización."
    return action_label(a) + "."


def _resource(row, n: _Names) -> str:
    rtype, rid = row["resource_type"], row["resource_id"]
    if not rtype or rid is None:
        return ""
    if rtype == "case":
        return "Caso " + n.case(rid).replace("el caso ", "")
    if rtype == "document":
        return "Documento " + n.doc(rid).replace("el documento ", "")
    if rtype == "user":
        return "Cuenta: " + n.user(rid)
    if rtype == "team":
        return "Equipo " + n.team(rid).replace("el equipo ", "")
    if rtype == "assistant_conversation":
        return f"Conversación #{rid}"
    if rtype == "grant":
        return f"Concesión #{rid}"
    return f"{rtype} #{rid}"


def present(db_path, rows, visible_cases: Optional[Set[int]] = None) -> List[dict]:
    """Filas listas para la vista: hora local, usuario, etiqueta, recurso y frase."""
    names = _Names(db_path, visible_cases)
    result = []
    for row in rows:
        try:
            details = json.loads(row["details"]) if row["details"] else {}
        except (ValueError, TypeError):
            details = {}
        try:
            sentence = _sentence(row, details if isinstance(details, dict) else {}, names)
        except Exception:                     # un evento antiguo con datos inesperados no rompe la página
            sentence = action_label(row["action"]) + "."
        result.append({
            "when": local_time(row["created_at"]),
            "who": names.user(row["user_id"]) if row["user_id"] is not None else (row["username"] or "—"),
            "username": row["username"],
            "action": row["action"],
            "label": action_label(row["action"]),
            "resource": _resource(row, names),
            "result": row["result"],
            "result_label": RESULT_LABELS.get(row["result"], row["result"]),
            "sentence": sentence,
            "reason": row["reason"] or "",
            "ip": row["ip"] or "",
        })
    return result
