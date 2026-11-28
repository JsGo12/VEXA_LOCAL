"""Ajustes que el administrador cambia desde la app (tabla app_settings, migración 10).

Hoy solo guarda el modelo de chat. Lo elegido aquí tiene prioridad sobre VEXA_CHAT_MODEL del .env;
si nunca se eligió nada, se respeta el .env (y si este también está vacío, la selección automática).
"""
from __future__ import annotations

from pathlib import Path

from vexa.database import connect
from vexa.rag import model_select

CHAT_MODEL_KEY = "chat_model"
AUTO = "auto"


def get(db_path: Path, key: str) -> str | None:
    with connect(db_path) as db:
        row = db.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def put(db_path: Path, key: str, value: str, user_id: int | None) -> None:
    with connect(db_path) as db:
        db.execute(
            "INSERT INTO app_settings(key, value, updated_by, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_by = excluded.updated_by, "
            "updated_at = excluded.updated_at",
            (key, value, user_id))


def chat_model_choice(db_path: Path) -> str | None:
    """'auto', un modelo concreto, o None si el administrador nunca eligió (manda el .env)."""
    return get(db_path, CHAT_MODEL_KEY)


def effective_forced_model(db_path: Path, env_model: str | None) -> str | None:
    """Modelo forzado que debe usar model_select (None = automático según RAM)."""
    choice = chat_model_choice(db_path)
    if choice is None:
        return env_model or None
    return None if choice == AUTO else choice


def apply_chat_model(db_path: Path, env_model: str | None) -> None:
    model_select.configurar(effective_forced_model(db_path, env_model))


def set_chat_model(db_path: Path, choice: str, user_id: int, env_model: str | None) -> None:
    if choice != AUTO and choice not in model_select.NIVELES_DICT:
        raise ValueError("Modelo no permitido.")
    put(db_path, CHAT_MODEL_KEY, choice, user_id)
    apply_chat_model(db_path, env_model)
