"""Carpeta vigilada: los archivos que se copian a <base>/<id_caso>/ se agregan solos a ese caso."""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Set, Tuple

import vault

LOGGER = logging.getLogger(__name__)


class CarpetaVigilada(threading.Thread):
    def __init__(self, base: Path, ingerir: Callable[[int, Path], bool], extensiones: Set[str],
                 intervalo: float = 5.0):
        super().__init__(daemon=True, name="vexa-carpeta-vigilada")
        self.base, self.ingerir, self.extensiones, self.intervalo = Path(base), ingerir, extensiones, intervalo
        self._vistos: Dict[Path, Tuple[int, int]] = {}
        self._parar = threading.Event()

    def escanear_una_vez(self) -> List[Path]:
        """Un archivo se procesa cuando su tamaño/fecha no cambió entre dos revisiones (ya terminó de copiarse)."""
        procesados = []
        if not self.base.is_dir():
            return procesados
        for carpeta in self.base.iterdir():
            if not (carpeta.is_dir() and carpeta.name.isdigit()):
                continue
            for f in carpeta.iterdir():
                if (not f.is_file() or f.name.startswith((".", "~$"))
                        or f.suffix.lower() not in self.extensiones):
                    continue
                st = f.stat()
                firma = (st.st_size, st.st_mtime_ns)
                if self._vistos.get(f) != firma:
                    self._vistos[f] = firma
                    continue
                try:
                    ok = bool(self.ingerir(int(carpeta.name), f))
                except Exception:
                    LOGGER.exception("No se pudo ingerir %s", f)
                    ok = False
                destino = carpeta / ("procesados" if ok else "errores")
                destino.mkdir(exist_ok=True)
                nombre_archivo = f"{time.strftime('%Y%m%d-%H%M%S')}_{time.time_ns()}_{f.name}"
                archivado = destino / nombre_archivo
                temporal = destino / (nombre_archivo + ".tmp")
                try:
                    # También se cifra el original archivado para que no quede una
                    # segunda copia legible en la carpeta vigilada.
                    vault.write_encrypted(temporal, f.read_bytes())
                    temporal.replace(archivado)
                    f.unlink()
                except Exception:
                    temporal.unlink(missing_ok=True)
                    raise
                self._vistos.pop(f, None)
                procesados.append(f)
        return procesados

    def run(self) -> None:
        while not self._parar.is_set():
            try:
                self.escanear_una_vez()
            except Exception:
                LOGGER.exception("Error revisando la carpeta vigilada")
            self._parar.wait(self.intervalo)

    def detener(self) -> None:
        self._parar.set()
