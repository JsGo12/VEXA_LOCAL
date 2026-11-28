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
