"""datos_demo.py: instalación de demostración con datos ficticios, siempre en una carpeta nueva."""
import datos_demo
import pytest

from vexa.database import connect
from vexa.permissions import policy
from vexa.services import cases as case_service
from vexa.services import users as user_service


@pytest.fixture
def demo(tmp_path):
    target = tmp_path / "demo"
    assert datos_demo.main([str(target)]) == 0
    return target


def test_demo_creates_people_cases_and_activity(demo):
    db_path = demo / "vexa_web.db"
    assert user_service.authenticate(db_path, "luis", datos_demo.DEMO_PASSWORD) is not None
    assert user_service.authenticate(db_path, "admin", datos_demo.DEMO_PASSWORD) is not None
    with connect(db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM users WHERE must_change_password = 1").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == len(datos_demo.CASES)
        assert db.execute("SELECT COUNT(*) FROM documents").fetchone()[0] >= len(datos_demo.CASES)
        closed = db.execute("SELECT progress, close_reason FROM cases WHERE status = 'cerrado'").fetchone()
        assert (closed["progress"], closed["close_reason"]) == (90, "acuerdo")
        assert db.execute("SELECT COUNT(*) FROM case_messages WHERE kind = 'mensaje'").fetchone()[0] == len(
            datos_demo.MESSAGES)
    states = {case_service.deadline_state(c["due_at"], c["status"]) for c in case_service.all_cases(db_path)}
    assert {"vencido", "pronto", "al_dia", "cerrado"} <= states
    assert not (demo / "credenciales_admin_inicial.txt").exists()


def test_demo_respects_the_permission_model(demo):
    db_path = demo / "vexa_web.db"
    with connect(db_path) as db:
        luis = db.execute("SELECT * FROM users WHERE username = 'luis'").fetchone()
        jefa = db.execute("SELECT * FROM users WHERE username = 'jefa'").fetchone()
        titles = {r["id"]: r["title"] for r in db.execute("SELECT id, title FROM cases")}
        luis_cases = {titles[i] for i in policy.case_scope(db, luis)}
        jefa_cases = {titles[i] for i in policy.case_scope(db, jefa)}
    assert luis_cases == {"Despido injustificado Pérez", "Arriendo impago Gómez"}
    assert luis_cases <= jefa_cases                     # la jefa supervisa a Luis
    assert "Divorcio de mutuo acuerdo Díaz" not in jefa_cases     # Pedro no está a su cargo


def test_demo_never_writes_into_a_folder_with_data(tmp_path):
    target = tmp_path / "real"
    target.mkdir()
    (target / "vexa_web.db").write_bytes(b"datos reales")
    with pytest.raises(SystemExit):
        datos_demo.main([str(target)])
    assert (target / "vexa_web.db").read_bytes() == b"datos reales"
