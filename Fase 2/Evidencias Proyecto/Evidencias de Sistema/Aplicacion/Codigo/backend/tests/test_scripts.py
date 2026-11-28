"""Scripts de línea de comandos del servidor: init_env.py y clave_recuperacion.py."""
import clave_recuperacion
import init_env
import pytest

from helpers import _web_app
from vexa.security import recovery, vault


def test_build_env_only_fills_the_secret_when_asked():
    example = "VEXA_ENV=production\nVEXA_SECRET_KEY=\nVEXA_PORT=5000"
    assert init_env.build_env(example, False) == example + "\n"
    filled = init_env.build_env(example, True).splitlines()
    assert filled[0] == "VEXA_ENV=production" and filled[2] == "VEXA_PORT=5000"
    assert filled[1].startswith("VEXA_SECRET_KEY=") and len(filled[1]) > len("VEXA_SECRET_KEY=") + 40


def test_init_env_creates_the_file_once_and_never_overwrites(tmp_path):
    target = tmp_path / ".env"
    assert init_env.main(["--target", str(target)]) == 0
    created = target.read_text(encoding="utf-8")
    assert "VEXA_HOST=" in created
    target.write_text("VEXA_PORT=5200\n", encoding="utf-8")       # valores del administrador
    assert init_env.main(["--target", str(target), "--generate-secret-key"]) == 0
    assert target.read_text(encoding="utf-8") == "VEXA_PORT=5200\n"


@pytest.fixture
def server(monkeypatch, tmp_path):
    web = _web_app(monkeypatch, tmp_path)
    vault.key_bytes()                                               # asegura que exista vault.key
    monkeypatch.setattr(clave_recuperacion, "load_settings", lambda: web.settings)
    return web


def test_recovery_key_cli_refuses_cloud_folders(server, tmp_path):
    with pytest.raises(SystemExit):
        clave_recuperacion.main([str(tmp_path / "OneDrive" / "clave.vexakey")])


def test_recovery_key_cli_creates_a_file_that_opens_with_the_password(server, tmp_path, monkeypatch):
    answers = iter(["una contraseña larga", "una contraseña larga"])
    monkeypatch.setattr(clave_recuperacion.getpass, "getpass", lambda _prompt: next(answers))
    destination = tmp_path / "usb" / "vexa-clave.vexakey"
    destination.parent.mkdir()
    assert clave_recuperacion.main([str(destination)]) == 0
    assert recovery.load_recovery(destination, "una contraseña larga") == vault.key_bytes()


def test_recovery_key_cli_rejects_mismatched_passwords(server, tmp_path, monkeypatch):
    answers = iter(["una contraseña larga", "otra contraseña distinta"])
    monkeypatch.setattr(clave_recuperacion.getpass, "getpass", lambda _prompt: next(answers))
    with pytest.raises(SystemExit):
        clave_recuperacion.main([str(tmp_path / "clave.vexakey")])
    assert not (tmp_path / "clave.vexakey").exists()
