"""Arranque del servidor: Waitress (predeterminado) o servidor de desarrollo de Flask, solo en loopback.

- Un único proceso servidor por carpeta de datos (bloqueo de archivo `vexa_server.lock`): evita dos
  carpetas vigiladas y dos indexaciones compitiendo sobre la misma base.
- `server.json` anuncia el puerto local del proceso activo para que Electron se conecte a él en vez de
  iniciar un segundo servidor. No contiene secretos.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import List, Optional, Tuple

from vexa.config import ConfigError, Settings, load_settings
from vexa.security import network

LOGGER = logging.getLogger("vexa.server")
LOCK_NAME = "vexa_server.lock"
INFO_NAME = "server.json"
EXIT_CONFIG, EXIT_ALREADY_RUNNING, EXIT_STARTUP = 2, 3, 4


class AlreadyRunning(RuntimeError):
    pass


class InstanceLock:
    """Bloqueo exclusivo liberado automáticamente por el sistema si el proceso termina."""

    def __init__(self, data_dir: Path):
        self.path = Path(data_dir) / LOCK_NAME
        self.info = Path(data_dir) / INFO_NAME
        self._fh = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self.path, "a+b")
        try:
            if sys.platform == "win32":
                import msvcrt
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            fh.close()
            raise AlreadyRunning("Ya hay un servidor VEXA activo con esta carpeta de datos.") from exc
        self._fh = fh

    def publish(self, listeners: List[Tuple[str, int]]) -> None:
        local_port = listeners[0][1]
        payload = {"pid": os.getpid(), "port": local_port,
                   "listen": [f"{h}:{p}" for h, p in listeners]}
        tmp = self.info.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, self.info)

    def release(self) -> None:
        try:
            self.info.unlink(missing_ok=True)
        except OSError:
            pass
        if self._fh is not None:
            try:
                if sys.platform == "win32":
                    import msvcrt
                    self._fh.seek(0)
                    msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
            self._fh.close()
            self._fh = None


def build(settings: Optional[Settings] = None, detect=network.detect_tailscale_ipv4):
    """Valida la configuración y crea la app. Devuelve (app, settings, listeners)."""
    settings = settings or load_settings()
    listeners = network.listen_addresses(settings, detect=detect)
    from vexa import create_app
    app = create_app(settings, listeners=listeners)
    return app, settings, listeners


def serve(settings: Optional[Settings] = None, *, dev: bool = False) -> int:
    try:
        settings = settings or load_settings()
    except ConfigError as exc:
        print(f"Configuración inválida: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    lock = InstanceLock(settings.data_dir)
    try:
        lock.acquire()
    except AlreadyRunning as exc:
        LOGGER.error("%s Ciérralo antes de iniciar otro.", exc)
        return EXIT_ALREADY_RUNNING
    try:
        try:
            app, settings, listeners = build(settings)
        except ConfigError as exc:
            LOGGER.error("Configuración inválida: %s", exc)
            return EXIT_CONFIG
        from vexa.services.background import start_background_services
        start_background_services(app)
        lock.publish(listeners)
        use_flask = dev or settings.server == "flask"
        LOGGER.info("VEXA (%s, %s) escuchando en: %s", settings.env, "flask-dev" if use_flask else "waitress",
                    ", ".join(f"http://{h}:{p}" for h, p in listeners))
        if settings.tailscale_enabled:
            LOGGER.info("Acceso remoto privado habilitado solo para la red Tailscale (sin Funnel).")
        if use_flask:
            if settings.is_production:
                LOGGER.error("El servidor de desarrollo no se permite en producción.")
                return EXIT_CONFIG
            if len(listeners) > 1:
                LOGGER.warning("El modo de desarrollo solo escucha en loopback; Tailscale requiere Waitress.")
            app.run(host=listeners[0][0], port=listeners[0][1], debug=False, threaded=True, use_reloader=False)
        else:
            from waitress import serve as waitress_serve
            waitress_serve(app, listen=network.format_listen(listeners), threads=settings.threads,
                           ident="VEXA", clear_untrusted_proxy_headers=True, channel_timeout=300)
        return 0
    except OSError as exc:
        LOGGER.error("No se pudo abrir el puerto (%s). ¿La dirección existe y el puerto está libre?", exc.strerror or exc)
        return EXIT_STARTUP
    finally:
        lock.release()
