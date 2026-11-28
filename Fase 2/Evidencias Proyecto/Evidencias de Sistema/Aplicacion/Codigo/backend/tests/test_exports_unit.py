"""Pruebas unitarias de la exportación a Excel."""
import io

from openpyxl import load_workbook

from vexa.services import exports


def test_audit_export_has_headers_and_highlights_denials():
    fila = {"when": "01-11-2026 10:00:00", "who": "Ana", "username": "ana", "label": "Descarga",
            "sentence": "Ana intentó descargar un documento", "result": "denied", "result_label": "Denegado",
            "reason": "sin permiso", "ip": "127.0.0.1"}
    libro = load_workbook(io.BytesIO(exports.audit_xlsx([fila])))
    hoja = libro["Auditoría"]
    assert hoja["A1"].value == "Fecha y hora"
    assert hoja["G2"].value == "sin permiso"
    assert hoja["A2"].fill.fgColor.rgb.endswith("FDE2E4")


def test_follow_up_export_includes_summary():
    caso = {"id": 7, "title": "Arriendo", "reference": "", "team_name": "Civil", "status_label": "En curso",
            "progress": 40, "due_at": "2026-11-30T12:00", "deadline_state": "pronto", "document_count": 2}
    data = {"cases": [caso], "overdue": [], "due_soon": [caso], "stale": []}
    libro = load_workbook(io.BytesIO(exports.follow_up_xlsx(data, {"pronto": "Vence pronto"})))
    hoja = libro["Seguimiento"]
    assert [hoja["B2"].value, hoja["C2"].value, hoja["G2"].value] == ["#7", "Equipo Civil", "Vence pronto"]
    resumen = {r[0]: r[1] for r in libro["Resumen"].iter_rows(min_row=2, max_row=5, values_only=True)}
    assert resumen == {"Total": 1, "Vencidos": 0, "Vencen en 7 días": 1, "Sin actualizaciones de avance": 0}
