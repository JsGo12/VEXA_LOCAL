"""VEXA — búsqueda híbrida, chunking por cláusulas y memoria de conversación.

Se apoya en rag_core.py (extracción, BM25, prompt base) sin romper su API.
Si el modelo de embeddings no está disponible, todo sigue funcionando solo con BM25.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional, Set, Tuple

import numpy as np
from rank_bm25 import BM25Okapi

import formats
import rag_core
import vault
from rag_core import Chunk, IndiceDocumental, _tokenizar

LOGGER = logging.getLogger(__name__)

EMBED_MODEL = os.environ.get("VEXA_EMBED_MODEL", "bge-m3")
CHUNKER_VERSION = "v2"
CHUNK_TARGET_CHARS = 900
CHUNK_MAX_CHARS = 1400
MAX_CONTEXT_CHARS = 4500          # tope de texto enviado al modelo (num_ctx=2048)
CANDIDATES = 20
RRF_K = 60
HISTORY_TURNS = 3

ProgressCb = Callable[[float, str], None]


# ------------------------------------------------------------------ chunking
_CLAUSE_RE = re.compile(
    r"^\s*(?:CL[ÁA]USULA|ART[ÍI]CULO|ART\.|CAP[ÍI]TULO|SECCI[ÓO]N|"
    r"PRIMERO|SEGUNDO|TERCERO|CUARTO|QUINTO|SEXTO|S[ÉE]PTIMO|OCTAVO|NOVENO|D[ÉE]CIMO|"
    r"\d{1,2}[\.\)]\s|[IVX]{1,5}[\.\)]\s)",
    re.IGNORECASE,
)
_SENT_RE = re.compile(r"(?<=[\.\;\:\!\?])\s+(?=[A-ZÁÉÍÓÚÑ0-9\"“(])")


def _unidades(texto: str) -> List[str]:
    """Parte el texto en unidades lógicas: párrafos, y cada cláusula abre una nueva."""
    unidades: List[str] = []
    actual: List[str] = []
    for linea in texto.splitlines():
        if not linea.strip():
            if actual:
                unidades.append(" ".join(actual)); actual = []
            continue
        if _CLAUSE_RE.match(linea) and actual:
            unidades.append(" ".join(actual)); actual = []
        actual.append(linea.strip())
    if actual:
        unidades.append(" ".join(actual))
    return unidades


def _partir_largo(unidad: str, maximo: int) -> List[str]:
    """Unidad demasiado larga: se corta SOLO entre oraciones, nunca a mitad de frase."""
    if len(unidad) <= maximo:
        return [unidad]
    piezas, buf = [], ""
    for oracion in _SENT_RE.split(unidad):
        if buf and len(buf) + len(oracion) + 1 > maximo:
            piezas.append(buf); buf = oracion
        else:
            buf = f"{buf} {oracion}".strip()
    if buf:
        piezas.append(buf)
    return piezas


def chunkear(doc_name: str, paginas: List[dict]) -> Tuple[List[Chunk], bool]:
    """Devuelve (chunks, es_ficha). Las fichas repetidas (Cliente 1, 2...) quedan completas."""
    if not paginas:
        return [], False
    todo = "\n".join(p["text"] for p in paginas)
    patron = rag_core._detectar_encabezado_registro(todo)
    if patron is not None:
        return rag_core._dividir_por_registros(doc_name, paginas, patron), True

    chunks: List[Chunk] = []
    buf, buf_ini, buf_fin = "", None, None

    def cerrar():
        nonlocal buf, buf_ini, buf_fin
        if buf.strip():
            chunks.append(Chunk(doc_name=doc_name, page_number=buf_ini, page_number_fin=buf_fin,
                                chunk_index=len(chunks), text=buf.strip()))
        buf, buf_ini, buf_fin = "", None, None

    for pagina in paginas:
        for unidad in _unidades(pagina["text"]):
            for pieza in _partir_largo(unidad, CHUNK_MAX_CHARS):
                es_clausula = bool(_CLAUSE_RE.match(pieza))
                if buf and (len(buf) + len(pieza) > CHUNK_TARGET_CHARS or (es_clausula and len(buf) > 300)):
                    cerrar()
                if buf_ini is None:
                    buf_ini = pagina["page_number"]
                buf = f"{buf}\n{pieza}" if buf else pieza
                buf_fin = pagina["page_number"]
    cerrar()
    return chunks, False


# ---------------------------------------------------------------- embeddings
def _embed(textos: List[str], modelo: str, host: str = rag_core.OLLAMA_HOST) -> Optional[np.ndarray]:
    """Embeddings normalizados vía Ollama; None si el modelo/servidor no está disponible."""
    try:
        cliente = rag_core.cliente_ollama(host)
        salida = []
        for i in range(0, len(textos), 16):
            resp = cliente.embed(model=modelo, input=textos[i:i + 16], keep_alive="30m")
            salida.extend(resp["embeddings"])
        m = np.asarray(salida, dtype=np.float32)
        return m / np.clip(np.linalg.norm(m, axis=1, keepdims=True), 1e-9, None)
    except Exception as exc:
        LOGGER.warning("Embeddings no disponibles (%s): se usará solo BM25. %s", modelo, type(exc).__name__)
        return None


# -------------------------------------------------------------------- índice
@dataclass
class IndiceHibrido(IndiceDocumental):
    vectores: Optional[np.ndarray] = None
    docs_ficha: Set[str] = field(default_factory=set)
    modelo_emb: str = EMBED_MODEL
    posicion: Dict[Tuple[str, int], int] = field(default_factory=dict)

    @property
    def semantico(self) -> bool:
        return self.vectores is not None


def _armar(chunks: List[Chunk], vectores, fichas: Set[str], modelo: str) -> IndiceHibrido:
    base = rag_core.construir_indice(chunks)
    idx = IndiceHibrido(chunks=base.chunks, bm25=base.bm25, docs_ficha=set(fichas), modelo_emb=modelo)
    idx.posicion = {(c.doc_name, c.chunk_index): p for p, c in enumerate(idx.chunks)}
    if vectores:
        idx.vectores = np.vstack(vectores)
    return idx


def construir_indice_hibrido(
    rutas: List[str],
    db_path=None,
    progreso: Optional[ProgressCb] = None,
    modelo_emb: str = EMBED_MODEL,
    nombres: Optional[Dict[str, str]] = None,
    parcial: Optional[Callable[["IndiceHibrido", int, int], None]] = None,
) -> IndiceHibrido:
    """Cada archivo se procesa una sola vez (caché en SQLite por hash del contenido descifrado).
    `nombres` mapea ruta almacenada -> nombre original para citar fuentes. `parcial` recibe un
    índice BM25 con lo ya leído tras cada archivo (permite preguntar mientras carga)."""
    import store
    progreso = progreso or (lambda p, m: None)
    nombres = nombres or {}
    todos: List[Chunk] = []
    vectores: List[np.ndarray] = []
    semantico = True
    fichas: Set[str] = set()
    usados: Set[str] = set()
    n = max(1, len(rutas))

    for i, ruta in enumerate(rutas):
        nombre = nombres.get(ruta) or os.path.basename(ruta)
        if nombre in usados:
            k = 2
            while f"{nombre} ({k})" in usados:
                k += 1
            nombre = f"{nombre} ({k})"
        usados.add(nombre)
        base = i / n
        progreso(base, f"Leyendo {nombre}")
        datos = vault.read_bytes(ruta)
        sha = hashlib.sha256(datos).hexdigest()
        filas = store.load_chunks(db_path, sha, CHUNKER_VERSION) if db_path else None
        if filas is not None:
            chunks = [Chunk(doc_name=nombre, page_number=p, page_number_fin=pe, chunk_index=idx, text=t)
                      for idx, p, pe, t in filas]
            es_ficha = rag_core._detectar_encabezado_registro("\n".join(c.text for c in chunks)) is not None
        else:
            chunks, es_ficha = chunkear(nombre, formats.extraer(ruta, datos))
            if db_path and chunks:
                store.save_chunks(db_path, sha, CHUNKER_VERSION,
                                  [(c.chunk_index, c.page_number, c.page_number_fin, c.text) for c in chunks])
        if es_ficha:
            fichas.add(nombre)
        if not chunks:
            continue

        if semantico:
            progreso(base + 0.5 / n, f"Analizando significado de {nombre}")
            mat = store.load_vectors(db_path, sha, CHUNKER_VERSION, modelo_emb, len(chunks)) if db_path else None
            if mat is None:
                mat = _embed([c.text for c in chunks], modelo_emb)
                if mat is not None and db_path:
                    store.save_vectors(db_path, sha, CHUNKER_VERSION, modelo_emb, mat)
            if mat is None:
                semantico = False
            else:
                vectores.append(mat)
        todos.extend(chunks)
        if parcial and i < len(rutas) - 1:
            parcial(_armar(todos, None, fichas, modelo_emb), i + 1, len(rutas))

    progreso(0.95, "Construyendo índice")
    idx = _armar(todos, vectores if (semantico and vectores) else None, fichas, modelo_emb)
    progreso(1.0, "Listo")
    return idx


# ------------------------------------------------------------------ búsqueda
_EXACTO_RE = re.compile(r"\d{3,}|\d{1,2}\.?\d{3}\.?\d{3}-[\dkK]")


def _ranking(scores: np.ndarray, n: int) -> List[int]:
    orden = np.argsort(-scores)[:n]
    return [int(i) for i in orden if scores[i] > 0]


def buscar_hibrido(pregunta: str, indice: IndiceHibrido, top_k: int,
                   vector_pregunta: Optional[np.ndarray] = None) -> List[Chunk]:
    """BM25 (palabras exactas, nombres, RUT, números) + vectores (significado), fusionados con RRF."""
    if indice.esta_vacio():
        return []
    tokens = _tokenizar(pregunta)
    puntajes: Dict[int, float] = {}
    peso_bm25 = 1.5 if _EXACTO_RE.search(pregunta) else 1.0

    if tokens and indice.bm25 is not None:
        for r, pos in enumerate(_ranking(np.asarray(indice.bm25.get_scores(tokens)), CANDIDATES)):
            puntajes[pos] = puntajes.get(pos, 0) + peso_bm25 / (RRF_K + r + 1)

    if indice.semantico:
        q = vector_pregunta if vector_pregunta is not None else _embed([pregunta], indice.modelo_emb)
        if q is not None and q.shape[1] == indice.vectores.shape[1]:
            sims = indice.vectores @ q[0]
            for r, pos in enumerate(_ranking(sims - 0.2, CANDIDATES)):   # descarta similitud muy baja
                puntajes[pos] = puntajes.get(pos, 0) + 1.0 / (RRF_K + r + 1)

    if not puntajes:  # sin coincidencias: respaldo léxico de rag_core
        return rag_core.buscar_contexto_relevante(pregunta, indice, top_k=top_k)
    mejores = sorted(puntajes, key=puntajes.get, reverse=True)[:top_k]
    return [indice.chunks[p] for p in mejores]


def con_vecinos(fragmentos: List[Chunk], indice: IndiceHibrido) -> List[Chunk]:
    """Agrega el fragmento anterior y el siguiente (salvo en fichas, que ya van completas)."""
    vistos, salida = set(), []
    for frag in fragmentos:
        candidatos = [frag]
        if frag.doc_name not in indice.docs_ficha:
            for delta in (-1, 1):
                pos = indice.posicion.get((frag.doc_name, frag.chunk_index + delta))
                if pos is not None:
                    candidatos.append(indice.chunks[pos])
        for c in sorted(candidatos, key=lambda c: (c.doc_name, c.chunk_index)):
            clave = (c.doc_name, c.chunk_index)
            if clave not in vistos:
                vistos.add(clave); salida.append(c)
    return salida


def limitar_contexto(fragmentos: List[Chunk], originales: List[Chunk],
                     maximo: int = MAX_CONTEXT_CHARS) -> List[Chunk]:
    """Prioriza los fragmentos que acertó la búsqueda; los vecinos entran mientras quepan."""
    clave = lambda c: (c.doc_name, c.chunk_index)
    prioridad = {clave(c) for c in originales}
    elegidos, total = [], 0
    for c in sorted(fragmentos, key=lambda c: clave(c) not in prioridad):
        if total + len(c.text) > maximo and elegidos:
            continue
        elegidos.append(c); total += len(c.text)
    return sorted(elegidos, key=lambda c: (c.doc_name, c.chunk_index))


# ------------------------------------------------------ memoria de conversación
_SEGUIMIENTO_RE = re.compile(
    r"^(y\b|¿y\b|entonces\b|ademas\b|además\b)|\b(su|sus|ese|esa|esos|esas|el otro|la otra|los otros|"
    r"lo mismo|anterior|mismo|misma)\b", re.IGNORECASE)

PROMPT_REFORMULAR = (
    "Reescribe la ÚLTIMA pregunta como una pregunta completa e independiente, usando la conversación "
    "para resolver referencias como 'su', 'el otro' o 'eso'. Responde SOLO con la pregunta reescrita, "
    "sin explicaciones."
)


def parece_seguimiento(pregunta: str) -> bool:
    return len(pregunta.split()) <= 7 or bool(_SEGUIMIENTO_RE.search(pregunta))


def _historial_texto(historial: List[dict]) -> str:
    return "\n".join(
        f"{'Usuario' if m['role'] == 'user' else 'Asistente'}: {m['content'][:300]}"
        for m in historial[-HISTORY_TURNS * 2:])


def reformular_pregunta(pregunta: str, historial: List[dict], modelo: str,
                        host: str = rag_core.OLLAMA_HOST) -> str:
    """Convierte '¿y su teléfono?' en una pregunta autónoma. Ante cualquier fallo devuelve la original."""
    if not historial or not parece_seguimiento(pregunta):
        return pregunta
    try:
        resp = rag_core.cliente_ollama(host).chat(
            model=modelo,
            messages=[{"role": "system", "content": PROMPT_REFORMULAR},
                      {"role": "user", "content": f"Conversación:\n{_historial_texto(historial)}\n\n"
                                                  f"Última pregunta: {pregunta}"}],
            options={"temperature": 0, "num_predict": 80, "num_ctx": 1536},
            keep_alive="30m",
        )
        nueva = resp["message"]["content"].strip().splitlines()[0].strip(' "')
        return nueva if 3 <= len(nueva) <= 300 else pregunta
    except Exception:
        LOGGER.warning("No se pudo reformular la pregunta; se usa la original.")
        return pregunta


PROMPT_SISTEMA = rag_core.PROMPT_SISTEMA + (
    "- Si la pregunta es de Sí/No, empieza con 'Sí.' o 'No.' y añade UNA frase breve; "
    "no uses listas ni mezcles respuestas contradictorias.\n"
    "- Si varias cláusulas parecen relacionadas, usa solo la que trata exactamente el tema preguntado.\n"
)


def consultar_stream(pregunta: str, fragmentos: List[Chunk], historial: List[dict], modelo: str,
                     host: str = rag_core.OLLAMA_HOST, opciones: Optional[dict] = None) -> Iterator[str]:
    """Streaming con las últimas vueltas de la conversación para entender el hilo."""
    if not fragmentos:
        yield "No encontré información relevante en los documentos del caso para responder esta pregunta."
        return
    mensajes = [{"role": "system", "content": PROMPT_SISTEMA}]
    for m in historial[-HISTORY_TURNS * 2:]:
        mensajes.append({"role": m["role"], "content": m["content"][:400]})
    mensajes.append({"role": "user", "content": rag_core.construir_prompt(pregunta, fragmentos)})
    stream = rag_core.cliente_ollama(host).chat(
        model=modelo, messages=mensajes, options=opciones or {}, keep_alive="30m", stream=True)
    try:
        for parte in stream:
            texto = parte["message"]["content"]
            if texto:
                yield texto
    finally:
        cerrar = getattr(stream, "close", None)
        if callable(cerrar):
            cerrar()


def precargar_modelo(modelo: str, host: str = rag_core.OLLAMA_HOST) -> None:
    """Deja el modelo de chat en memoria para que la primera respuesta no espere la carga."""
    try:
        rag_core.cliente_ollama(host).chat(model=modelo, messages=[{"role": "user", "content": "hola"}],
                                           options={"num_predict": 1}, keep_alive="30m")
    except Exception:
        LOGGER.info("No se pudo precargar %s (Ollama apagado o modelo ausente).", modelo)
