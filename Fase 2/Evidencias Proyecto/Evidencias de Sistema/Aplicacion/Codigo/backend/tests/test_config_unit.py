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
