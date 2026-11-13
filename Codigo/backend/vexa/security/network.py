"""Red privada: direcciones de escucha, detección de Tailscale y filtro de origen.

Política:
- Siempre se escucha en 127.0.0.1 (uso local y Electron).
- Con TAILSCALE_ENABLED=true se agrega un segundo listener SOLO en la IP de Tailscale del equipo
  (100.64.0.0/10). Nunca se usa 0.0.0.0 ni '::'.
- Defensa en profundidad: aunque el socket esté bien acotado, cada petición se rechaza si su IP de
  origen no es loopback o (con Tailscale activo) del rango de Tailscale.
"""
from __future__ import annotations

import ipaddress
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from vexa.config import (TAILSCALE_V4, TAILSCALE_V6, ConfigError, Settings, is_loopback_host,
                         is_tailscale_address)

LOGGER = logging.getLogger(__name__)
_WINDOWS_TAILSCALE = Path(r"C:\Program Files\Tailscale\tailscale.exe")


def tailscale_cli() -> Optional[str]:
    found = shutil.which("tailscale")
    if found:
        return found
    return str(_WINDOWS_TAILSCALE) if _WINDOWS_TAILSCALE.is_file() else None


def detect_tailscale_ipv4(timeout: float = 5.0) -> Optional[str]:
    """IP 100.x de este equipo según `tailscale ip -4` o, si no hay CLI (contenedor Docker que
    comparte la red de Tailscale), según la interfaz de Tailscale. No envía datos a ningún lado."""
    cli = tailscale_cli()
    if cli:
        try:
            out = subprocess.run([cli, "ip", "-4"], capture_output=True, text=True, timeout=timeout,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
        except (OSError, subprocess.SubprocessError):
            out = ""
        for line in out.split():
            if is_tailscale_address(line):
                return line.strip()
    return tailscale_interface_ipv4()


def tailscale_interface_ipv4(interfaces=None) -> Optional[str]:
    """IPv4 100.x de una interfaz llamada «tailscale…» (tailscale0 en Linux, «Tailscale» en Windows).

    Se exige el nombre de la interfaz además del rango: 100.64.0.0/10 también es el rango CGNAT de
    algunos proveedores, y escuchar ahí expondría VEXA a la red del proveedor."""
    if interfaces is None:
        try:
            import psutil
            interfaces = psutil.net_if_addrs()
        except Exception:
            return None
    for name, addrs in interfaces.items():
        if not str(name).lower().startswith("tailscale"):
            continue
        for addr in addrs:
            ip = getattr(addr, "address", "")
            if is_tailscale_address(ip) and ipaddress.ip_address(ip).version == 4:
                return ip
    return None


def listen_addresses(settings: Settings, detect=detect_tailscale_ipv4) -> List[Tuple[str, int]]:
    """Pares (host, puerto) donde escuchará Waitress. Valida todo antes de abrir sockets."""
    if not is_loopback_host(settings.host):
        raise ConfigError("VEXA_HOST debe ser una dirección de loopback.")
    listeners = [(settings.host, settings.port)]
    if settings.tailscale_enabled:
        address = settings.tailscale_bind_address or detect()
        if not address:
            raise ConfigError(
                "TAILSCALE_ENABLED=true pero no se encontró la IP de Tailscale. Inicia sesión en "
                "Tailscale o define TAILSCALE_BIND_ADDRESS con la IP 100.x de este equipo."
            )
        if not (is_tailscale_address(address) or is_loopback_host(address)):
            raise ConfigError("La dirección de Tailscale detectada no pertenece al rango privado de Tailscale.")
        pair = (address, settings.tailscale_port or settings.port)
        if pair not in listeners:
            listeners.append(pair)
    return listeners


def format_listen(listeners: Iterable[Tuple[str, int]]) -> str:
    """Formato del parámetro `listen` de Waitress (IPv6 entre corchetes)."""
    parts = []
    for host, port in listeners:
        parts.append(f"[{host}]:{port}" if ":" in host else f"{host}:{port}")
    return " ".join(parts)


def trusted_hosts(settings: Settings, listeners: Iterable[Tuple[str, int]]) -> List[str]:
    hosts = {"127.0.0.1", "localhost", "::1", "[::1]"}
    for host, _port in listeners:
        hosts.add(host)
    if settings.tailscale_enabled and settings.tailscale_host:
        hosts.add(settings.tailscale_host)
        hosts.add(settings.tailscale_host.split(".")[0])
    return sorted(hosts)


class RemoteAddressFilter:
    """Middleware WSGI: responde 403 a orígenes fuera de loopback/Tailscale antes de llegar a Flask."""

    def __init__(self, wsgi_app, allow_tailscale: bool):
        self.wsgi_app = wsgi_app
        self.allow_tailscale = allow_tailscale

    def allowed(self, remote: Optional[str]) -> bool:
        if not remote:
            return False
        try:
            ip = ipaddress.ip_address(remote.split("%")[0])
        except ValueError:
            return False
        if getattr(ip, "ipv4_mapped", None):
            ip = ip.ipv4_mapped
        if ip.is_loopback:
            return True
        return self.allow_tailscale and ip in (TAILSCALE_V4 if ip.version == 4 else TAILSCALE_V6)

    def __call__(self, environ, start_response):
        if not self.allowed(environ.get("REMOTE_ADDR")):
            LOGGER.warning("Conexión rechazada desde un origen no autorizado: %s", environ.get("REMOTE_ADDR"))
            start_response("403 Forbidden", [("Content-Type", "text/plain; charset=utf-8")])
            return ["Acceso denegado: VEXA solo acepta conexiones locales o de Tailscale.".encode("utf-8")]
        return self.wsgi_app(environ, start_response)
