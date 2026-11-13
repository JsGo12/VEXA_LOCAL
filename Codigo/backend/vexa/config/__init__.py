"""Configuración central de VEXA.

Orden de precedencia (de mayor a menor):
1. Variables de entorno del proceso (por ejemplo, las que fija Electron).
2. Archivo `.env` (no se versiona; ver `.env.example`).
3. Valores predeterminados seguros definidos aquí.

Ningún valor secreto se imprime ni se registra en logs: `Settings.__repr__` los oculta.
"""
from __future__ import annotations

import ipaddress
import os
import sys
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Mapping, Optional
from urllib.parse import urlparse

BACKEND_DIR = Path(__file__).resolve().parents[2]          # Codigo/backend
PROJECT_DIR = BACKEND_DIR.parent                           # Codigo/
FROZEN = bool(getattr(sys, "frozen", False))
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", PROJECT_DIR / "frontend"))
DEFAULT_DATA_DIR = Path.home() / ".vexa_local"
TAILSCALE_V4 = ipaddress.ip_network("100.64.0.0/10")
TAILSCALE_V6 = ipaddress.ip_network("fd7a:115c:a1e0::/48")
_TRUE = {"1", "true", "yes", "si", "sí", "on"}
_FALSE = {"0", "false", "no", "off", ""}


class ConfigError(ValueError):
    """La configuración no es válida; el mensaje nunca incluye secretos."""


def _secret_field(**kwargs):
    return field(repr=False, **kwargs)


@dataclass(frozen=True)
class Settings:
    env: str = "development"
    host: str = "127.0.0.1"
    port: int = 5000
    threads: int = 8
    server: str = "waitress"
    log_level: str = "INFO"
    data_dir: Path = DEFAULT_DATA_DIR
    db_path: Path = DEFAULT_DATA_DIR / "vexa_web.db"
    watch_dir: Path = DEFAULT_DATA_DIR / "carpeta_vigilada"
    secret_key: Optional[str] = _secret_field(default=None)
    session_cookie_secure: bool = False
    ollama_host: str = "http://127.0.0.1:11434"
    chat_model: Optional[str] = None
    embed_model: str = "bge-m3"
    ollama_keep_alive: str = "5m"
    tesseract_cmd: Optional[str] = None
    admin_username: str = "admin"
    admin_password: Optional[str] = _secret_field(default=None)
    tailscale_enabled: bool = False
    tailscale_bind_address: Optional[str] = None
    tailscale_port: Optional[int] = None
    tailscale_host: Optional[str] = None
    max_file_size: int = 30 * 1024 * 1024
    env_file: Optional[Path] = None

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "case_documents"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    def safe_summary(self) -> dict:
        """Resumen apto para logs: sin secretos."""
        hidden = {"secret_key", "admin_password"}
        out = {}
        for f in fields(self):
            value = getattr(self, f.name)
            out[f.name] = ("<definida>" if value else "<vacía>") if f.name in hidden else str(value)
        return out


# --------------------------------------------------------------------- lectura
def _candidate_env_files(environ: Mapping[str, str]) -> list[Path]:
    explicit = environ.get("VEXA_ENV_FILE")
    if explicit:
        return [Path(explicit)]
    if FROZEN:  # instalador: junto al ejecutable o en la carpeta de datos
        return [Path(sys.executable).resolve().parent / ".env", DEFAULT_DATA_DIR / ".env"]
    return [PROJECT_DIR / ".env"]


def read_env_file(path: Path) -> dict[str, str]:
    """Lee un .env sin modificar os.environ (python-dotenv, sin interpolación de comandos)."""
    from dotenv import dotenv_values

    return {k: v for k, v in dotenv_values(path, interpolate=False).items() if v is not None}


def _bool(name: str, raw: Optional[str], default: bool) -> bool:
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise ConfigError(f"{name} debe ser true o false.")


def _int(name: str, raw: Optional[str], default: Optional[int], lo: int, hi: int) -> Optional[int]:
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError as exc:
        raise ConfigError(f"{name} debe ser un número entero.") from exc
    if not lo <= value <= hi:
        raise ConfigError(f"{name} debe estar entre {lo} y {hi}.")
    return value


def is_loopback_host(host: str) -> bool:
    if host.strip().lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip().strip("[]")).is_loopback
    except ValueError:
        return False


def is_tailscale_address(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host.strip().strip("[]"))
    except ValueError:
        return False
    return ip in (TAILSCALE_V4 if ip.version == 4 else TAILSCALE_V6)


def load_settings(environ: Optional[Mapping[str, str]] = None, env_file: Optional[Path] = None,
                  use_env_file: bool = True) -> Settings:
    """Construye y valida la configuración. Lanza ConfigError con un mensaje accionable."""
    process_env = dict(os.environ if environ is None else environ)
    file_values: dict[str, str] = {}
    used_file = None
    if use_env_file:
        for candidate in ([env_file] if env_file else _candidate_env_files(process_env)):
            if candidate and candidate.is_file():
                file_values, used_file = read_env_file(candidate), candidate
                break
    merged = {**file_values, **process_env}           # el entorno del proceso tiene prioridad

    def get(name: str) -> Optional[str]:
        value = merged.get(name)
        return value.strip() if isinstance(value, str) else value

    env = (get("VEXA_ENV") or "development").lower()
    if env not in {"development", "production"}:
        raise ConfigError("VEXA_ENV debe ser development o production.")

    host = get("VEXA_HOST") or "127.0.0.1"
    if host in {"0.0.0.0", "::", "*"} or not is_loopback_host(host):
        raise ConfigError(
            "VEXA_HOST solo admite direcciones de loopback (127.0.0.1). Para acceso remoto "
            "privado usa TAILSCALE_ENABLED=true; VEXA nunca escucha en todas las interfaces."
        )
    port = _int("VEXA_PORT", get("VEXA_PORT"), 5000, 1, 65535)
    threads = _int("VEXA_THREADS", get("VEXA_THREADS"), 8, 1, 64)

    server = (get("VEXA_SERVER") or "waitress").lower()
    if server not in {"waitress", "flask"}:
        raise ConfigError("VEXA_SERVER debe ser waitress o flask.")
    if server == "flask" and env == "production":
        raise ConfigError("El servidor de desarrollo de Flask no se permite con VEXA_ENV=production.")

    log_level = (get("VEXA_LOG_LEVEL") or "INFO").upper()
    if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ConfigError("VEXA_LOG_LEVEL debe ser DEBUG, INFO, WARNING, ERROR o CRITICAL.")

    data_dir = Path(get("VEXA_DATA_DIR") or DEFAULT_DATA_DIR).expanduser()
    db_path = Path(get("VEXA_DB_PATH") or (data_dir / "vexa_web.db")).expanduser()
    watch_dir = Path(get("VEXA_WATCH_DIR") or (data_dir / "carpeta_vigilada")).expanduser()

    secret_key = get("VEXA_SECRET_KEY") or None
    if secret_key is not None and len(secret_key) < 32:
        raise ConfigError("VEXA_SECRET_KEY debe tener al menos 32 caracteres (o dejarse vacía).")

    ollama_host = get("OLLAMA_HOST") or "http://127.0.0.1:11434"
    if "://" not in ollama_host:
        ollama_host = "http://" + ollama_host
    parsed = urlparse(ollama_host)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or not is_loopback_host(parsed.hostname):
        raise ConfigError(
            "OLLAMA_HOST debe apuntar a este mismo equipo (127.0.0.1 o localhost): VEXA no envía "
            "documentos ni consultas a servidores de IA externos."
        )

    admin_password = get("VEXA_ADMIN_PASSWORD") or None
    if admin_password is not None and len(admin_password) < 12:
        raise ConfigError("VEXA_ADMIN_PASSWORD debe tener al menos 12 caracteres.")

    ts_enabled = _bool("TAILSCALE_ENABLED", get("TAILSCALE_ENABLED"), False)
    ts_bind = get("TAILSCALE_BIND_ADDRESS") or None
    ts_port = _int("TAILSCALE_PORT", get("TAILSCALE_PORT"), None, 1, 65535)
    ts_host = get("TAILSCALE_HOST") or None
    if ts_bind is not None:
        if ts_bind in {"0.0.0.0", "::", "*"}:
            raise ConfigError("TAILSCALE_BIND_ADDRESS no puede ser 0.0.0.0 ni ::; usa la IP 100.x de Tailscale.")
        if not (is_tailscale_address(ts_bind) or is_loopback_host(ts_bind)):
            raise ConfigError(
                "TAILSCALE_BIND_ADDRESS debe ser una IP de Tailscale (100.64.0.0/10 o fd7a:115c:a1e0::/48)."
            )
    if ts_host is not None and any(ch in ts_host for ch in "/:@ "):
        raise ConfigError("TAILSCALE_HOST debe ser solo un nombre de equipo (MagicDNS), sin esquema ni puerto.")

    return Settings(
        env=env, host="127.0.0.1" if host.lower() == "localhost" else host, port=port, threads=threads,
        server=server, log_level=log_level, data_dir=data_dir, db_path=db_path, watch_dir=watch_dir,
        secret_key=secret_key,
        session_cookie_secure=_bool("VEXA_SESSION_COOKIE_SECURE", get("VEXA_SESSION_COOKIE_SECURE"), False),
        ollama_host=ollama_host.rstrip("/"), chat_model=get("VEXA_CHAT_MODEL") or None,
        embed_model=get("VEXA_EMBED_MODEL") or "bge-m3",
        ollama_keep_alive=get("VEXA_OLLAMA_KEEP_ALIVE") or "5m",
        tesseract_cmd=get("VEXA_TESSERACT_CMD") or None,
        admin_username=get("VEXA_ADMIN_USERNAME") or "admin", admin_password=admin_password,
        tailscale_enabled=ts_enabled, tailscale_bind_address=ts_bind, tailscale_port=ts_port,
        tailscale_host=ts_host, env_file=used_file,
    )
