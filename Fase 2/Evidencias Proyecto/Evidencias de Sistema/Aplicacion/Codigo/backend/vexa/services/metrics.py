"""Métricas del estudio para el administrador: casos por estado, tiempo de cierre y carga por abogado.

Solo metadatos (estados, fechas, asignaciones): nunca títulos de documentos, notas ni contenido.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from vexa.database import connect
from vexa.services.cases import STATUS_LABELS, all_cases, deadline_state


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "").replace(" ", "T"))
    except ValueError:
        return None


def _close_days(db_path: Path) -> list[float]:
    """Días entre la creación de cada caso cerrado y su último cierre registrado."""
    with connect(db_path) as db:
        rows = db.execute("""
            SELECT c.created_at AS opened, MAX(u.created_at) AS closed
            FROM cases c JOIN case_updates u ON u.case_id = c.id AND u.status = 'cerrado'
            WHERE c.status = 'cerrado' GROUP BY c.id""").fetchall()
    days = []
    for row in rows:
        opened, closed = _parse(row["opened"]), _parse(row["closed"])
        if opened and closed and closed >= opened:
            days.append((closed - opened).total_seconds() / 86400)
    return days


def _workload(db_path: Path, cases) -> list[dict]:
    """Casos abiertos por abogado: asignados directamente y por equipo (un caso de equipo cuenta para cada
    integrante), con cuántos están vencidos."""
    with connect(db_path) as db:
        people = db.execute("SELECT id, name FROM users WHERE active = 1 AND role IN ('lawyer', 'chief_lawyer') "
                            "ORDER BY name").fetchall()
        members = {}
        for row in db.execute("SELECT team_id, user_id FROM team_members"):
            members.setdefault(row["team_id"], set()).add(row["user_id"])
    load = {p["id"]: {"name": p["name"], "open": 0, "overdue": 0} for p in people}
    for case in cases:
        if case["status"] == "cerrado":
            continue
        owners = {case["assigned_user_id"]} if case["assigned_user_id"] else members.get(case["team_id"], set())
        late = deadline_state(case["due_at"], case["status"]) == "vencido"
        for owner in owners:
            if owner in load:
                load[owner]["open"] += 1
                load[owner]["overdue"] += int(late)
    ranked = sorted(load.values(), key=lambda p: (-p["open"], p["name"]))
    top = max((p["open"] for p in ranked), default=0)
    for p in ranked:
        p["share"] = round(100 * p["open"] / top) if top else 0
    return ranked


def firm_metrics(db_path: Path) -> dict:
    cases = all_cases(db_path)
    total = len(cases)
    by_status = []
    for key, label in STATUS_LABELS.items():
        count = sum(1 for c in cases if c["status"] == key)
        by_status.append({"key": key, "label": label, "count": count,
                          "share": round(100 * count / total) if total else 0})
    states = [deadline_state(c["due_at"], c["status"]) for c in cases]
    days = _close_days(db_path)
    return {
        "total": total,
        "open": sum(1 for c in cases if c["status"] != "cerrado"),
        "overdue": states.count("vencido"),
        "due_soon": states.count("pronto"),
        "by_status": by_status,
        "closed_count": len(days),
        "avg_close_days": round(sum(days) / len(days), 1) if days else None,
        "workload": _workload(db_path, cases),
    }
