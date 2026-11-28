"""Prioridad de uso del modelo local: las consultas de personas van primero.

Ollama atiende las peticiones de a una (o pocas) a la vez. Si el resumen automático de un caso está
generando texto cuando alguien pregunta en el chat, la pregunta queda en cola detrás del resumen.
Para evitarlo:
- el chat y el asistente marcan su trabajo con `interactive()`;
- el trabajo de fondo llama a `esperar_turno()` antes de cada llamada al modelo y espera mientras haya
  consultas en curso (y unos segundos después, para no meterse entre la reformulación y la respuesta).
"""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager

GRACE_SECONDS = 3.0          # pausa tras la última consulta antes de retomar el fondo
MAX_WAIT_SECONDS = 600.0     # nunca bloquear el fondo para siempre

_cond = threading.Condition()
_state = {"active": 0, "last_end": 0.0}


@contextmanager
def interactive():
    """Marca una consulta de una persona (chat o asistente) mientras dura."""
    with _cond:
        _state["active"] += 1
    try:
        yield
    finally:
        with _cond:
            _state["active"] -= 1
            _state["last_end"] = time.monotonic()
            _cond.notify_all()


def interactive_active() -> int:
    with _cond:
        return _state["active"]


def esperar_turno(grace: float = GRACE_SECONDS, max_wait: float = MAX_WAIT_SECONDS) -> bool:
    """Bloquea al trabajo de fondo mientras haya consultas. Devuelve False si se agotó la espera."""
    deadline = time.monotonic() + max_wait
    with _cond:
        while True:
            now = time.monotonic()
            idle_for = now - _state["last_end"]
            if _state["active"] == 0 and idle_for >= grace:
                return True
            if now >= deadline:
                return False
            pause = (grace - idle_for) if _state["active"] == 0 else 1.0
            _cond.wait(timeout=max(0.05, min(pause, deadline - now)))
