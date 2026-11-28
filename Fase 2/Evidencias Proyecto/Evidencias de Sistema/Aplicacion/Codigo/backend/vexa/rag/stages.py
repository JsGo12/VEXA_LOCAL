"""Fase 2: resúmenes automáticos y preguntas de totalidad respondidas por etapas (map-reduce)."""
from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterator
from typing import Any

from vexa.rag import core as rag_core
from vexa.rag import prompts
from vexa.rag.core import Chunk, IndiceDocumental

LOGGER = logging.getLogger(__name__)
MAX_LOTE_CHARS = 3000
MAX_LOTES_RESUMEN = 6
MAX_LOTES_TOTALIDAD = 30

_TOTALIDAD_RE = re.compile(
    r"\b(todos|todas|lista|listado|listame|enumera|enumerame|cu[aá]ntos|cu[aá]ntas|en total|"
    r"resumen completo|todo el (documento|expediente|contrato))\b", re.IGNORECASE)

# Textos en vexa/rag/prompts.py
PROMPT_RESUMEN = prompts.PROMPT_RESUMEN
PROMPT_RESUMEN_FINAL = prompts.PROMPT_RESUMEN_FINAL
PROMPT_EXTRAER = prompts.PROMPT_EXTRAER
PROMPT_FINAL = prompts.PROMPT_FINAL


def es_totalidad(pregunta: str) -> bool:
    return bool(_TOTALIDAD_RE.search(pregunta))


def _llamar(modelo: str, system: str, user: str, opciones: dict[str, Any] | None = None,
            host: str | None = None) -> str:
    r = rag_core.cliente_ollama(host).chat(
        model=modelo, keep_alive=rag_core.OLLAMA_KEEP_ALIVE,
        options={"temperature": 0, "num_predict": 300, **(opciones or {})},
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
    return r["message"]["content"].strip()


def lotes(chunks: list[Chunk], max_chars: int = MAX_LOTE_CHARS) -> list[list[Chunk]]:
    grupos, actual, n = [], [], 0
    for c in chunks:
        if actual and (n + len(c.text) > max_chars or actual[-1].doc_name != c.doc_name):
            grupos.append(actual); actual, n = [], 0
        actual.append(c); n += len(c.text)
    if actual:
        grupos.append(actual)
    return grupos


def _texto(lote: list[Chunk]) -> str:
    return "\n\n".join(f"[{c.fuente}]\n{c.text}" for c in lote)


def resumir_indice(indice: IndiceDocumental, modelo: str, host: str | None = None,
                   max_lotes: int = MAX_LOTES_RESUMEN,
                   opciones: dict[str, Any] | None = None,
                   antes_de_llamar: Callable[[], Any] | None = None) -> str:
    """Resumen por lotes. `antes_de_llamar` se ejecuta antes de cada llamada al modelo (el servicio
    de fondo lo usa para ceder el turno a las consultas del chat)."""
    esperar = antes_de_llamar or (lambda: None)
    grupos = lotes(indice.chunks)
    if not grupos:
        return ""
    if len(grupos) > max_lotes:   # muestreo parejo para cubrir inicio, medio y final
        pos = sorted({round(i * (len(grupos) - 1) / (max_lotes - 1)) for i in range(max_lotes)})
        grupos = [grupos[p] for p in pos]
    parciales = []
    for g in grupos:
        esperar()
        parciales.append(_llamar(modelo, PROMPT_RESUMEN, _texto(g), opciones, host))
    if len(parciales) == 1:
        return parciales[0]
    esperar()
    return _llamar(modelo, PROMPT_RESUMEN_FINAL, "\n\n".join(parciales), opciones, host)


def responder_por_etapas(pregunta: str, indice: IndiceDocumental, modelo: str,
                         opciones: dict[str, Any], max_chars: int,
                         host: str | None = None,
                         max_lotes: int = MAX_LOTES_TOTALIDAD,
                         chunks: list[Chunk] | None = None) -> Iterator[dict[str, Any]]:
    """Eventos: {'type':'progress'}, {'type':'delta'}, {'type':'sources'}.
    Etapa 1: extrae datos de cada bloque. Etapa 2: consolida. Etapa 3: respuesta final en vivo."""
    grupos = lotes(indice.chunks if chunks is None else chunks)
    if not grupos:
        yield {"type": "delta", "text": "No encontré información relacionada en los documentos del caso."}
        yield {"type": "sources", "sources": []}
        return
    truncado = len(grupos) > max_lotes
    grupos = grupos[:max_lotes]
    extractos, fuentes, vistos = [], [], set()
    for i, g in enumerate(grupos):
        yield {"type": "progress", "done": i, "total": len(grupos)}
        salida = _llamar(modelo, PROMPT_EXTRAER, prompts.PLANTILLA_EXTRAER.format(pregunta=pregunta, texto=_texto(g)),
                         opciones, host)
        lineas = [l.strip(" -•\t") for l in salida.splitlines() if l.strip()]
        if not lineas or lineas[0].upper().startswith("NADA"):
            continue
        for l in lineas:
            if l.casefold() not in vistos:
                vistos.add(l.casefold()); extractos.append(l)
        fuentes.extend(c.fuente for c in g)
    if not extractos:
        yield {"type": "delta", "text": "No encontré información relacionada en los documentos del caso."}
        yield {"type": "sources", "sources": []}
        return

    yield {"type": "progress", "done": len(grupos), "total": len(grupos)}
    datos = "\n".join(extractos)
    if len(datos) > max_chars:      # consolidación jerárquica para no desbordar el contexto
        partes, cur = [], ""
        for l in extractos:
            if cur and len(cur) + len(l) > max_chars // 2:
                partes.append(cur); cur = ""
            cur += l + "\n"
        partes.append(cur)
        datos = "\n".join(_llamar(modelo, prompts.PROMPT_CONSOLIDAR, p, opciones, host)
                          for p in partes)[:max_chars]

    stream = rag_core.cliente_ollama(host).chat(
        model=modelo, stream=True, keep_alive=rag_core.OLLAMA_KEEP_ALIVE, options=opciones,
        messages=[{"role": "system", "content": PROMPT_FINAL},
                  {"role": "user", "content": prompts.PLANTILLA_FINAL.format(datos=datos, pregunta=pregunta)}])
    try:
        for parte in stream:
            t = parte["message"]["content"]
            if t:
                yield {"type": "delta", "text": t}
    finally:
        cerrar = getattr(stream, "close", None)
        if callable(cerrar):
            cerrar()
    if truncado:
        yield {"type": "delta", "text": f"\n\n(Nota: el expediente es muy extenso; se revisaron los primeros {max_lotes} bloques.)"}
    yield {"type": "sources", "sources": list(dict.fromkeys(fuentes))}
