"""Elige el modelo de chat de Ollama según la RAM/GPU del computador y lo que esté instalado."""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import List, Optional, Set

import rag_core

# (modelo, num_ctx, caracteres máximos de contexto), de mayor a menor capacidad
NIVELES = [
    ("llama3.1:8b", 4096, 9000),
    ("llama3.2", 4096, 8000),
    ("llama3.2:1b", 2048, 4500),
]
NIVELES_DICT = {m: (c, ch) for m, c, ch in NIVELES}
_cache = {"t": 0.0, "perfil": None}


@dataclass(frozen=True)
class Perfil:
    modelo: str
    num_ctx: int
    max_chars: int

    @property
    def opciones(self) -> dict:
        return {"num_ctx": self.num_ctx, "num_batch": 128, "num_predict": 256, "temperature": 0.1}


def hardware() -> tuple[Optional[float], float]:
    """(RAM en GB o None, VRAM NVIDIA en GB; 0 si no hay GPU NVIDIA)."""
    ram = None
    try:
        import psutil
        ram = psutil.virtual_memory().total / 1024 ** 3
    except Exception:
        pass
    vram = 0.0
    if shutil.which("nvidia-smi"):
        try:
            out = subprocess.run(["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True, timeout=4).stdout
            vram = max((float(x) for x in out.split() if x.replace(".", "").isdigit()), default=0) / 1024
        except Exception:
            pass
    return ram, vram


def nivel_recomendado(ram: Optional[float], vram: float) -> int:
    """Índice en NIVELES: 0 = el más capaz."""
    if vram >= 6 or (ram or 0) >= 24:
        return 0
    if vram >= 3 or (ram or 0) >= 12:
        return 1
    return 2


def elegir(instalados: Set[str], ram: Optional[float], vram: float, forzado: Optional[str] = None) -> Perfil:
    if forzado:
        c, ch = NIVELES_DICT.get(forzado, (2048, 4500))
        return Perfil(forzado, c, ch)
    tengo = {n[:-7] if n.endswith(":latest") else n for n in instalados}
    for modelo, ctx, chars in NIVELES[nivel_recomendado(ram, vram):]:
        if modelo in tengo:
            return Perfil(modelo, ctx, chars)
    return Perfil(*NIVELES[-1])


def instalados_ollama() -> Set[str]:
    resp = rag_core.cliente_ollama(rag_core.OLLAMA_HOST).list()
    modelos = getattr(resp, "models", None)
    if modelos is None and isinstance(resp, dict):
        modelos = resp.get("models", [])
    nombres = set()
    for m in modelos or []:
        nombres.add((m.get("model") or m.get("name") or "") if isinstance(m, dict)
                    else (getattr(m, "model", None) or getattr(m, "name", "")))
    return nombres


def perfil_actual(ttl: float = 60.0) -> Perfil:
    """Perfil cacheado 60 s. VEXA_CHAT_MODEL fuerza un modelo concreto."""
    if _cache["perfil"] is not None and time.time() - _cache["t"] < ttl:
        return _cache["perfil"]
    try:
        inst = instalados_ollama()
    except Exception:
        inst = set()
    ram, vram = hardware()
    perfil = elegir(inst, ram, vram, os.environ.get("VEXA_CHAT_MODEL"))
    _cache.update(t=time.time(), perfil=perfil)
    return perfil
