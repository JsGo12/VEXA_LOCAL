"""Calendario de vencimientos: arma la vista mensual con las fechas límite de los casos que se pueden ver."""
from __future__ import annotations

import calendar
from datetime import date

from vexa.services.cases import deadline_state

MONTHS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
          "noviembre", "diciembre"]
WEEKDAYS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]


def parse_month(value: str | None, today: date | None = None) -> tuple[int, int]:
    """'2026-11' -> (2026, 11). Vacío o inválido = el mes actual."""
    today = today or date.today()
    try:
        year, month = (int(part) for part in (value or "").split("-"))
        if 2000 <= year <= 2100 and 1 <= month <= 12:
            return year, month
    except ValueError:
        pass
    return today.year, today.month


def shift(year: int, month: int, delta: int) -> str:
    index = year * 12 + (month - 1) + delta
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def month_view(cases, year: int, month: int, today: date | None = None) -> dict:
    """Semanas (lunes a domingo) con los casos que vencen cada día del mes pedido."""
    today = today or date.today()
    by_day: dict[int, list[dict]] = {}
    for case in cases:
        due = str(case["due_at"] or "")[:10]
        if due[:7] != f"{year:04d}-{month:02d}":
            continue
        by_day.setdefault(int(due[8:10]), []).append({
            "id": case["id"], "title": case["title"], "time": str(case["due_at"])[11:16],
            "state": deadline_state(case["due_at"], case["status"]),
        })
    weeks = []
    for week in calendar.Calendar(firstweekday=0).monthdayscalendar(year, month):
        weeks.append([{"day": d, "today": date(year, month, d) == today if d else False,
                       "cases": sorted(by_day.get(d, []), key=lambda c: c["time"])} if d else None
                      for d in week])
    return {"year": year, "month": month, "label": f"{MONTHS[month - 1].capitalize()} {year}",
            "weeks": weeks, "weekdays": WEEKDAYS, "total": sum(len(v) for v in by_day.values()),
            "prev": shift(year, month, -1), "next": shift(year, month, 1)}
