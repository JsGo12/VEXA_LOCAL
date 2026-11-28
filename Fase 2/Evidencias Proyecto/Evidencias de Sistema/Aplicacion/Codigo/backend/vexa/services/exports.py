"""Exportación a Excel (.xlsx) del panel de Seguimiento y del registro de Auditoría.

Solo metadatos: lo mismo que se ve en pantalla (sin notas, preguntas ni contenido de documentos).
"""
from __future__ import annotations

import io
from collections.abc import Iterable, Sequence
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

HEADER_FILL = PatternFill("solid", fgColor="4F52D9")
STATE_FILL = {"vencido": "FDE2E4", "pronto": "FDF1D6", "al_dia": "E3F5EC", "cerrado": "ECEEF2"}
RESULT_FILL = {"denied": "FDE2E4", "error": "FDF1D6"}


def _sheet(wb: Workbook, title: str, headers: Sequence[str], rows: Iterable[Sequence], widths: Sequence[int],
           fills: Iterable[str] = ()) -> None:
    ws = wb.active if wb.active.title == "Sheet" else wb.create_sheet()
    ws.title = title
    ws.append(list(headers))
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(vertical="center")
    fills = list(fills)
    for i, row in enumerate(rows):
        ws.append(list(row))
        color = fills[i] if i < len(fills) else None
        if color:
            for cell in ws[ws.max_row]:
                cell.fill = PatternFill("solid", fgColor=color)
    for idx, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = width
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions


def _bytes(wb: Workbook) -> bytes:
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def follow_up_xlsx(data: dict, deadline_labels: dict) -> bytes:
    wb = Workbook()
    cases: list[dict] = data["cases"]
    rows, fills = [], []
    for c in cases:
        rows.append([c["title"], c.get("reference") or f"#{c['id']}",
                     ("Equipo " + c["team_name"]) if c.get("team_name") else (c.get("assignee_name") or ""),
                     c["status_label"], c["progress"] / 100,
                     datetime.strptime(c["due_at"], "%Y-%m-%dT%H:%M"), deadline_labels[c["deadline_state"]],
                     c["document_count"], c.get("last_update") or "", c.get("last_activity") or ""])
        fills.append(STATE_FILL[c["deadline_state"]])
    _sheet(wb, "Seguimiento", ["Caso", "Referencia", "Responsable", "Estado", "Avance", "Fecha límite", "Plazo",
                               "Documentos", "Última actualización de avance", "Última actividad"],
           rows, [34, 14, 24, 13, 9, 17, 13, 11, 22, 20], fills)
    ws = wb["Seguimiento"]
    for row in ws.iter_rows(min_row=2):
        row[4].number_format = "0%"
        row[5].number_format = "dd-mm-yyyy hh:mm"
    summary = wb.create_sheet("Resumen")
    summary.append(["Indicador", "Casos"])
    for cell in summary[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = HEADER_FILL
    for label, value in [("Total", len(cases)), ("Vencidos", len(data["overdue"])),
                         ("Vencen en 7 días", len(data["due_soon"])),
                         ("Sin actualizaciones de avance", len(data["stale"]))]:
        summary.append([label, value])
    summary.column_dimensions["A"].width = 32
    summary.append([])
    summary.append([f"Generado el {datetime.now().strftime('%d-%m-%Y %H:%M')} desde VEXA"])
    return _bytes(wb)


def audit_xlsx(rows: list[dict]) -> bytes:
    wb = Workbook()
    _sheet(wb, "Auditoría", ["Fecha y hora", "Persona", "Usuario", "Acción", "Qué se hizo", "Resultado", "Motivo", "Origen"],
           ([r["when"], r["who"], r["username"] or "", r["label"], r["sentence"], r["result_label"],
             r["reason"] if r["result"] != "ok" else "", r["ip"]] for r in rows),
           [19, 22, 14, 22, 70, 11, 30, 16], (RESULT_FILL.get(r["result"]) for r in rows))
    return _bytes(wb)
