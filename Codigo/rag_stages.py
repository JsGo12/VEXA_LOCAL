"""Fase 2: resúmenes automáticos y preguntas de totalidad respondidas por etapas (map-reduce)."""
from __future__ import annotations

import logging
import re
from typing import Dict, Iterator, List, Optional

import rag_core
from rag_core import Chunk

LOGGER = logging.getLogger(__name__)
MAX_LOTE_CHARS = 3000
MAX_LOTES_RESUMEN = 6
MAX_LOTES_TOTALIDAD = 30

_TOTALIDAD_RE = re.compile(
    r"\b(todos|todas|lista|listado|listame|enumera|enumerame|cu[aá]ntos|cu[aá]ntas|en total|"
    r"resumen completo|todo el (documento|expediente|contrato))\b", re.IGNORECASE)

PROMPT_RESUMEN = ("Resume el texto en 2 o 3 frases en español, solo con lo que dice: de qué trata, "
                  "partes involucradas, fechas y montos relevantes. No inventes.")
PROMPT_RESUMEN_FINAL = ("Con estos resúmenes parciales, escribe un único resumen del expediente en 4 a 6 "
                        "líneas en español: tema, partes, fechas y montos clave. No inventes.")
PROMPT_EXTRAER = ("Del TEXTO, extrae SOLO los datos que responden a la PREGUNTA, una línea por elemento y "
                  "sin explicaciones. Si el texto no contiene nada relevante, responde exactamente: NADA")
PROMPT_FINAL = ("Responde la pregunta usando SOLO los datos extraídos. Incluye todos los elementos, sin "
                "repetir y sin inventar. Responde en español, breve y claro.")


def es_totalidad(pregunta: str) -> bool:
    return bool(_TOTALIDAD_RE.search(pregunta))


def _llamar(modelo: str, system: str, user: str, opciones: Optional[dict] = None,
            host: str = rag_core.OLLAMA_HOST) -> str:
    r = rag_core.cliente_ollama(host).chat(
        model=modelo, keep_alive="30m", options={"temperature": 0, "num_predict": 300, **(opciones or {})},
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
    return r["message"]["content"].strip()


def lotes(chunks: List[Chunk], max_chars: int = MAX_LOTE_CHARS) -> List[List[Chunk]]:
    grupos, actual, n = [], [], 0
    for c in chunks:
        if actual and (n + len(c.text) > max_chars or actual[-1].doc_name != c.doc_name):
            grupos.append(actual); actual, n = [], 0
        actual.append(c); n += len(c.text)
    if actual:
        grupos.append(actual)
    return grupos


def _texto(lote: List[Chunk]) -> str:
    return "\n\n".join(f"[{c.fuente}]\n{c.text}" for c in lote)


def resumir_indice(indice, modelo: str, host: str = rag_core.OLLAMA_HOST,
                   max_lotes: int = MAX_LOTES_RESUMEN, opciones: Optional[dict] = None) -> str:
    grupos = lotes(indice.chunks)
    if not grupos:
        return ""
    if len(grupos) > max_lotes:   # muestreo parejo para cubrir inicio, medio y final
        pos = sorted({round(i * (len(grupos) - 1) / (max_lotes - 1)) for i in range(max_lotes)})
        grupos = [grupos[p] for p in pos]
    parciales = [_llamar(modelo, PROMPT_RESUMEN, _texto(g), opciones, host) for g in grupos]
    if len(parciales) == 1:
        return parciales[0]
    return _llamar(modelo, PROMPT_RESUMEN_FINAL, "\n\n".join(parciales), opciones, host)


def responder_por_etapas(pregunta: str, indice, modelo: str, opciones: dict, max_chars: int,
                         host: str = rag_core.OLLAMA_HOST,
                         max_lotes: int = MAX_LOTES_TOTALIDAD) -> Iterator[Dict]:
    """Eventos: {'type':'progress'}, {'type':'delta'}, {'type':'sources'}.
    Etapa 1: extrae datos de cada bloque. Etapa 2: consolida. Etapa 3: respuesta final en vivo."""
    grupos = lotes(indice.chunks)
    truncado = len(grupos) > max_lotes
    grupos = grupos[:max_lotes]
    extractos, fuentes, vistos = [], [], set()
    for i, g in enumerate(grupos):
        yield {"type": "progress", "done": i, "total": len(grupos)}
        salida = _llamar(modelo, PROMPT_EXTRAER, f"PREGUNTA: {pregunta}\n\nTEXTO:\n{_texto(g)}", opciones, host)
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
        datos = "\n".join(_llamar(modelo, "Consolida esta lista sin repetir elementos ni inventar.", p, opciones, host)
                          for p in partes)[:max_chars]

    stream = rag_core.cliente_ollama(host).chat(
        model=modelo, stream=True, keep_alive="30m", options=opciones,
        messages=[{"role": "system", "content": PROMPT_FINAL},
                  {"role": "user", "content": f"DATOS EXTRAÍDOS:\n{datos}\n\nPREGUNTA: {pregunta}"}])
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
