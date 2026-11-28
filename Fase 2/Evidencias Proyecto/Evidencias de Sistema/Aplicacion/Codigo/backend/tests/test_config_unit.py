"""Pruebas unitarias de la validación de configuración (vexa.config)."""
import pytest

from vexa import config


def _load(**env):
    return config.load_settings(environ=env, use_env_file=False)


def test_bool_accepts_spanish_and_english_values():
    assert config._bool("X", "Sí", False) is True
    assert config._bool("X", " off ", True) is False
    assert config._bool("X", None, True) is True
    with pytest.raises(config.ConfigError):
        config._bool("X", "tal vez", False)


def test_int_validates_range_and_format():
    assert config._int("X", "", 5, 1, 10) == 5
    assert config._int("X", " 7 ", 5, 1, 10) == 7
    with pytest.raises(config.ConfigError):
        config._int("X", "11", 5, 1, 10)
    with pytest.raises(config.ConfigError):
        config._int("X", "abc", 5, 1, 10)


def test_loopback_detection():
    for host in ("127.0.0.1", "127.0.0.2", "::1", "[::1]", "localhost", " LOCALHOST "):
        assert config.is_loopback_host(host), host
    for host in ("192.168.0.1", "100.64.0.1", "ejemplo.cl", ""):
        assert not config.is_loopback_host(host), host


def test_tailscale_address_ranges():
    assert config.is_tailscale_address("100.64.0.1")
    assert config.is_tailscale_address("100.127.255.254")
    assert config.is_tailscale_address("fd7a:115c:a1e0::1")
    assert not config.is_tailscale_address("100.128.0.1")
    assert not config.is_tailscale_address("nombre-equipo")


def test_host_must_be_loopback():
    for host in ("0.0.0.0", "::", "192.168.1.20"):
        with pytest.raises(config.ConfigError):
            _load(VEXA_HOST=host)
    assert _load(VEXA_HOST="localhost").host == "127.0.0.1"


def test_ollama_host_gets_scheme_and_must_be_local():
    assert _load(OLLAMA_HOST="localhost:11434/").ollama_host == "http://localhost:11434"
    with pytest.raises(config.ConfigError):
        _load(OLLAMA_HOST="http://10.0.0.5:11434")
    with pytest.raises(config.ConfigError):
        _load(OLLAMA_HOST="ftp://127.0.0.1")


def test_short_secrets_are_rejected():
    with pytest.raises(config.ConfigError):
        _load(VEXA_SECRET_KEY="corta")
    with pytest.raises(config.ConfigError):
        _load(VEXA_ADMIN_PASSWORD="123456")
    assert _load(VEXA_SECRET_KEY="x" * 32).secret_key == "x" * 32


def test_flask_server_is_not_allowed_in_production():
    with pytest.raises(config.ConfigError):
        _load(VEXA_ENV="production", VEXA_SERVER="flask")
    assert _load(VEXA_ENV="production").is_production
    with pytest.raises(config.ConfigError):
        _load(VEXA_ENV="staging")


def test_invalid_log_level_is_rejected():
    assert _load(VEXA_LOG_LEVEL="debug").log_level == "DEBUG"
    with pytest.raises(config.ConfigError):
        _load(VEXA_LOG_LEVEL="verbose")


def test_backup_dir_must_be_outside_data_dir(tmp_path):
    with pytest.raises(config.ConfigError):
        _load(VEXA_DATA_DIR=str(tmp_path), VEXA_BACKUP_DIR=str(tmp_path / "respaldos"))
    settings = _load(VEXA_DATA_DIR=str(tmp_path / "datos"), VEXA_BACKUP_DIR=str(tmp_path / "respaldos"))
    assert settings.backup_dir == tmp_path / "respaldos"


def test_tailscale_settings_are_validated():
    with pytest.raises(config.ConfigError):
        _load(TAILSCALE_BIND_ADDRESS="0.0.0.0")
    with pytest.raises(config.ConfigError):
        _load(TAILSCALE_BIND_ADDRESS="192.168.1.10")
    with pytest.raises(config.ConfigError):
        _load(TAILSCALE_HOST="vexa:443")
    assert _load(TAILSCALE_BIND_ADDRESS="100.70.1.2").tailscale_bind_address == "100.70.1.2"
