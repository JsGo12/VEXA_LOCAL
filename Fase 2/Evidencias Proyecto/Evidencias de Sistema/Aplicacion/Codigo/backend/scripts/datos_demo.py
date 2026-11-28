"""Crea una instalación de demostración de VEXA con datos 100 % ficticios (para la presentación).

Siempre en una carpeta de datos NUEVA, nunca en la real: si la carpeta ya tiene datos, no hace nada.

    .\\.venv\\Scripts\\python.exe backend\\scripts\\datos_demo.py C:\\VEXA_demo
    $env:VEXA_DATA_DIR='C:\\VEXA_demo'; .\\.venv\\Scripts\\python.exe backend\\run.py

Todas las cuentas usan la misma contraseña de demostración (se muestra al terminar).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # Codigo/backend

from vexa import create_app  # noqa: E402
from vexa.config import load_settings  # noqa: E402
from vexa.database import connect  # noqa: E402
from vexa.services import users as user_service  # noqa: E402

DEMO_PASSWORD = "Demo-VEXA-2026"

# (usuario, nombre, rol)
PEOPLE = [
    ("jefa", "Camila Rojas", "chief_lawyer"),
    ("luis", "Luis Fuentes", "lawyer"),
    ("ana", "Ana Morales", "lawyer"),
    ("pedro", "Pedro Soto", "lawyer"),
]
TEAM = ("Equipo Laboral", ["ana", "pedro"])
SUPERVISED_BY_CHIEF = ["luis", "ana"]


def prepare(data_dir: Path):
    """App de VEXA sobre una carpeta de datos nueva. Devuelve los ajustes."""
    if data_dir.exists() and any(data_dir.iterdir()):
        raise SystemExit(f"{data_dir} ya tiene archivos. Usa una carpeta nueva: los datos de demostración "
                         "nunca se mezclan con datos reales.")
    # Todo dentro de la carpeta nueva, aunque el .env real defina otras rutas (VEXA_DB_PATH, etc.).
    environ = {**os.environ, "VEXA_DATA_DIR": str(data_dir), "VEXA_DB_PATH": str(data_dir / "vexa_web.db"),
               "VEXA_WATCH_DIR": str(data_dir / "carpeta_vigilada"), "VEXA_ADMIN_PASSWORD": DEMO_PASSWORD,
               "VEXA_BACKUP_DIR": str(data_dir.parent / (data_dir.name + "_respaldos"))}
    settings = load_settings(environ)
    create_app(settings)                               # migra la base y crea el administrador
    with connect(settings.db_path) as db:              # demo: nadie debe cambiar la contraseña al entrar
        db.execute("UPDATE users SET must_change_password = 0")
    (data_dir / "credenciales_admin_inicial.txt").unlink(missing_ok=True)
    return settings


def create_people(settings) -> dict[str, int]:
    ids = {}
    for username, name, role in PEOPLE:
        ids[username] = user_service.create_user(settings.db_path, name, username, DEMO_PASSWORD, role)
    with connect(settings.db_path) as db:
        db.execute("UPDATE users SET must_change_password = 0")
        ids["admin"] = db.execute("SELECT id FROM users WHERE role = 'admin' ORDER BY id LIMIT 1").fetchone()[0]
    name, members = TEAM
    ids["team"] = user_service.create_team(settings.db_path, name, [ids[m] for m in members])
    user_service.set_supervised_lawyers(settings.db_path, ids["jefa"], [ids[m] for m in SUPERVISED_BY_CHIEF])
    return ids


# (título, referencia, responsable, días hasta la fecha límite, resumen, documentos {nombre: texto})
CASES = [
    ("Despido injustificado Pérez", "LAB-2026-014", "luis", -4,
     "Trabajador despedido sin carta de aviso; se reclama indemnización por años de servicio.",
     {"contrato_trabajo.txt": "Contrato de trabajo entre Comercial Andes SpA y Juan Pérez, cargo bodeguero, "
                              "sueldo base 650.000 pesos, jornada de 45 horas, inicio el 3 de marzo de 2019.",
      "carta_despido.txt": "Con fecha 2 de septiembre de 2026 se comunica el término del contrato por "
                           "necesidades de la empresa. No se adjunta finiquito."}),
    ("Arriendo impago Gómez", "CIV-2026-031", "luis", 3,
     "Arrendatario con tres meses de renta impaga; se evalúa demanda de término de arriendo.",
     {"contrato_arriendo.txt": "Contrato de arriendo del departamento 504, calle Los Aromos 1200. Renta "
                               "mensual 450.000 pesos, pagadera los primeros cinco días de cada mes.",
      "cobranza.txt": "Se adeudan las rentas de julio, agosto y septiembre de 2026, total 1.350.000 pesos."}),
    ("Accidente laboral Muñoz", "LAB-2026-022", "team", 20,
     "Caída en faena; se revisa responsabilidad del empleador y cobertura del seguro.",
     {"informe_accidente.txt": "El 14 de agosto de 2026 la trabajadora Rosa Muñoz cayó desde una escalera "
                               "sin arnés. Licencia médica de 30 días. Testigo: Carlos Vera."}),
    ("Cobro de factura Servicios Sur", "COM-2026-007", "ana", 45,
     "Factura vencida por servicios de mantención; se prepara gestión preparatoria de cobro.",
     {"factura_1182.txt": "Factura N.° 1182 de Servicios Sur Ltda. por 2.300.000 pesos, emitida el 10 de "
                          "junio de 2026, vencimiento a 30 días. Sin pagos registrados."}),
    ("Divorcio de mutuo acuerdo Díaz", "FAM-2026-003", "pedro", 60,
     "Acuerdo completo y suficiente en preparación: alimentos, cuidado personal y relación directa.",
     {"propuesta_acuerdo.txt": "Pensión de alimentos de 300.000 pesos mensuales para dos hijos. Cuidado "
                               "personal de la madre; relación directa con el padre fines de semana alternos."}),
    ("Revisión de contrato de software", "COM-2026-011", "jefa", 10,
     "Revisión de cláusulas de licencia, confidencialidad y multa por incumplimiento.",
     {"contrato_licencia.txt": "La licencia es no exclusiva por 24 meses. Multa de 5 % del valor anual por "
                               "cada semana de atraso en la entrega. Confidencialidad por 5 años."}),
]


def create_cases(settings, ids: dict[str, int]) -> dict[str, int]:
    from datetime import datetime, timedelta

    from vexa.services import cases as case_service
    case_ids = {}
    for title, reference, owner, days, summary, files in CASES:
        due_at = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%dT18:00")
        kind, assignee = ("team", ids["team"]) if owner == "team" else ("user", ids[owner])
        case_ids[title] = case_service.create_case(
            settings.db_path, settings.upload_dir, title=title, summary=summary, reference=reference,
            due_at=due_at, assignment_type=kind, assignee_id=assignee,
            files=[(name, text.encode("utf-8")) for name, text in files.items()], created_by=ids["admin"])
    return case_ids


# (caso, quién, estado, avance %, nota, motivo de cierre)
PROGRESS = [
    ("Despido injustificado Pérez", "jefa", "en_revision", 70, "Demanda redactada; falta revisar el cálculo.", ""),
    ("Arriendo impago Gómez", "jefa", "en_curso", 40, "Se envió carta de cobro al arrendatario.", ""),
    ("Divorcio de mutuo acuerdo Díaz", "admin", "cerrado", 90, "Las partes firmaron el acuerdo.", "acuerdo"),
]
# (caso, quién, nota del abogado)
NOTES = [
    ("Despido injustificado Pérez", "luis", "El cliente trae mañana las últimas tres liquidaciones."),
    ("Accidente laboral Muñoz", "ana", "Se pidió al empleador el registro de capacitación en altura."),
]
# (caso, quién, mensaje del equipo)
MESSAGES = [
    ("Despido injustificado Pérez", "luis", "Faltan documentos: el finiquito no aparece en la carpeta."),
    ("Despido injustificado Pérez", "jefa", "Lo pido a la empresa hoy. Revisa el plazo de caducidad."),
    ("Accidente laboral Muñoz", "pedro", "Subí el informe del accidente; reviso la licencia médica."),
]


def create_activity(settings, ids: dict[str, int], case_ids: dict[str, int]) -> None:
    from vexa.services import cases as case_service
    from vexa.services import messages as message_service
    with connect(settings.db_path) as db:
        names = {row["id"]: row["name"] for row in db.execute("SELECT id, name FROM users")}
    for title, who, status, progress, note, reason in PROGRESS:
        case_service.update_progress(settings.db_path, case_ids[title], ids[who], status, progress, note, reason)
    for title, who, note in NOTES:
        case_service.add_note(settings.db_path, case_ids[title], ids[who], note)
    for title, who, body in MESSAGES:
        message_service.post(settings.db_path, case_ids[title], {"id": ids[who], "name": names[ids[who]]}, body)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Crear datos de demostración de VEXA (ficticios)")
    parser.add_argument("carpeta", type=Path, help="carpeta de datos NUEVA para la demostración")
    args = parser.parse_args(argv)
    settings = prepare(args.carpeta.resolve())
    ids = create_people(settings)
    create_activity(settings, ids, create_cases(settings, ids))
    print(f"Datos de demostración creados en {settings.data_dir} ({len(CASES)} casos ficticios)")
    print(f"Usuarios: admin, {', '.join(p[0] for p in PEOPLE)} · contraseña: {DEMO_PASSWORD}")
    print(f"Para usarlos: $env:VEXA_DATA_DIR='{settings.data_dir}'; .\\.venv\\Scripts\\python.exe backend\\run.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
