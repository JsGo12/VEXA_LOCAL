"""Administración > Modelo IA: el administrador elige el modelo de chat desde la app."""
import pytest

from helpers import CSRF, _client_as, _web_app, add_user, admin_id
from vexa import create_app
from vexa.rag import model_select
from vexa.services import app_settings


@pytest.fixture
def web(monkeypatch, tmp_path):
    monkeypatch.setattr(model_select, "instalados_ollama", lambda: {"llama3.2:1b", "llama3.2:latest"})
    monkeypatch.setattr(model_select, "hardware", lambda: (16.0, 0.0))
    web = _web_app(monkeypatch, tmp_path)
    yield web
    model_select.configurar(None)          # no contaminar otras pruebas con el modelo elegido


def _choose(client, model):
    return client.post("/admin/modelo", data={"csrf_token": CSRF, "model": model})


def test_admin_sees_model_tab_with_hardware_and_installed_models(web):
    html = _client_as(web, admin_id(web)).get("/admin?tab=modelo").get_data(as_text=True)
    assert "Modelo de IA del chat" in html and "16 GB de RAM" in html
    assert "llama3.2:1b" in html and "ollama pull llama3.1:8b" in html     # el 8b no está instalado
    assert "Pide más memoria" not in html


def test_heavy_model_shows_a_memory_warning(web, monkeypatch):
    monkeypatch.setattr(model_select, "instalados_ollama", lambda: {"llama3.1:8b", "llama3.2:1b"})
    html = _client_as(web, admin_id(web)).get("/admin?tab=modelo").get_data(as_text=True)
    assert "Pide más memoria" in html                                       # 8b en un equipo de 16 GB


def test_admin_choice_applies_now_persists_and_is_audited(web):
    client = _client_as(web, admin_id(web))
    assert _choose(client, "llama3.2:1b").status_code == 302
    assert model_select.CHAT_MODEL == "llama3.2:1b"
    assert model_select.perfil_para(model_select.instalados_ollama()).modelo == "llama3.2:1b"
    model_select.configurar(None)
    create_app(web.settings)                                   # al reiniciar se vuelve a aplicar
    assert model_select.CHAT_MODEL == "llama3.2:1b"
    with web.connect_db() as db:
        row = db.execute("SELECT result FROM audit_log WHERE action = 'settings.chat_model'").fetchone()
    assert row["result"] == "ok"
    assert "Cambió el modelo de IA del chat a llama3.2:1b." in client.get("/admin/audit").get_data(as_text=True)


def test_auto_overrides_the_env_model_and_missing_models_are_rejected(web):
    client = _client_as(web, admin_id(web))
    response = _choose(client, "llama3.1:8b")                   # no instalado
    assert app_settings.chat_model_choice(web.db_path) is None
    assert "ollama pull llama3.1:8b" in client.get(response.headers["Location"]).get_data(as_text=True)
    assert _choose(client, "gpt-4").status_code == 302          # fuera de la lista: no se guarda
    assert app_settings.chat_model_choice(web.db_path) is None
    _choose(client, "auto")
    assert app_settings.effective_forced_model(web.db_path, "llama3.2") is None


def test_only_the_admin_can_change_the_model(web):
    lawyer = add_user(web, "luis")
    chief = add_user(web, "jefa", "chief_lawyer")
    assert _choose(_client_as(web, lawyer), "llama3.2:1b").status_code == 403
    _choose(_client_as(web, chief), "llama3.2:1b")
    assert app_settings.chat_model_choice(web.db_path) is None
    assert 'id="tab-modelo"' not in _client_as(web, chief).get("/admin?tab=modelo").get_data(as_text=True)
