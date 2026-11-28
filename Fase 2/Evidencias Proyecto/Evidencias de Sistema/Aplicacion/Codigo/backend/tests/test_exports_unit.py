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
