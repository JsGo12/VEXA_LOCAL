"""
Vexa Local — Motor RAG (núcleo, sin interfaz)
================================================

Piezas base del RAG que reutilizan `rag.hybrid`, `rag.stages` y `rag.firm`:
modelo de fragmentos (Chunk), índice BM25, tokenización, detección de fichas
repetidas, extracción de Word, armado del prompt y cliente de Ollama.
No depende de Flask ni de ninguna interfaz.

Todo el procesamiento ocurre en la máquina local. No se realiza ninguna
llamada a servicios externos: solo se habla con el servidor local de
Ollama (http://localhost:11434).
"""

from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from heapq import nlargest
from typing import Any, Dict, List, Optional

import ollama
from docx import Document as DocxDocument
from rank_bm25 import BM25Okapi

from vexa.rag import prompts

# =============================================================================
# CONFIGURACIÓN GLOBAL
# =============================================================================

# Cantidad de fragmentos de contexto que se recuperan por pregunta puntual.
TOP_K_FRAGMENTOS = 3

# Cantidad de fragmentos cuando la pregunta pide un LISTADO/TOTALIDAD de
# registros (ej. "todos los pacientes de X"), en vez de un registro puntual.
TOP_K_FRAGMENTOS_AGREGACION = 8

# Host del servidor local de Ollama. `vexa.create_app` lo reemplaza con el valor
# validado de OLLAMA_HOST (siempre una dirección de loopback).
OLLAMA_HOST = "http://127.0.0.1:11434"
OLLAMA_KEEP_ALIVE = os.environ.get("VEXA_OLLAMA_KEEP_ALIVE", "5m").strip() or "5m"


def configurar(host: Optional[str] = None, keep_alive: Optional[str] = None) -> None:
    """Aplica la configuración central (host de Ollama y keep_alive) al motor RAG."""
    global OLLAMA_HOST, OLLAMA_KEEP_ALIVE
    if host:
        OLLAMA_HOST = host
    if keep_alive is not None:
        OLLAMA_KEEP_ALIVE = str(keep_alive).strip() or "5m"


@lru_cache(maxsize=4)
def _cliente(host: str):
    return ollama.Client(host=host)


def cliente_ollama(host: Optional[str] = None):
    """Reutiliza el cliente HTTP para conservar conexiones y evitar recrearlo."""
    return _cliente(host or OLLAMA_HOST)


# =============================================================================
# MODELOS DE DATOS
# =============================================================================

@dataclass
class Chunk:
    """Representa un fragmento de texto extraído de un documento,
    conservando la metadata necesaria para poder citar la fuente."""

    doc_name: str
    page_number: int
    chunk_index: int
    text: str
    # Página final del fragmento, solo si un registro cruza un salto de
    # página del PDF (ej. una ficha de "Cliente N" partida entre dos
    # páginas). Si es None, se asume que el chunk vive en una sola página.
    page_number_fin: Optional[int] = None

    @property
    def fuente(self) -> str:
        """Etiqueta legible para citar este fragmento como fuente."""
        fin = self.page_number_fin or self.page_number
        if fin != self.page_number:
            return f"{self.doc_name} — páginas {self.page_number}-{fin}"
        return f"{self.doc_name} — página {self.page_number}"


@dataclass
class IndiceDocumental:
    """Contenedor del índice BM25 junto con los chunks originales."""

    chunks: List[Chunk] = field(default_factory=list)
    bm25: Optional[BM25Okapi] = None

    def esta_vacio(self) -> bool:
        return len(self.chunks) == 0


# =============================================================================
# MÓDULO DE PROCESAMIENTO DE DOCUMENTOS
# =============================================================================

def tokenizar(texto: str) -> List[str]:
    """Tokeniza texto para BM25: minúsculas, sin tildes, solo palabras.

    BM25 funciona por coincidencia léxica exacta, por lo que normalizar
    (quitar tildes/mayúsculas) mejora el recall en español sin necesidad
    de embeddings.
    """
    texto = texto.lower()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.findall(r"[a-z0-9]+", texto)


def extraer_texto_docx(
    ruta_o_archivo, parrafos_por_pagina: int = 25
) -> List[Dict[str, Any]]:
    """Extrae el texto de un archivo .docx, simulando 'páginas' agrupando
    bloques de contenido, ya que Word no guarda paginación real en su
    estructura interna.

    IMPORTANTE: recorre el documento en su orden real (párrafos y tablas
    intercalados tal como aparecen), incluyendo el texto de celdas de
    tablas — `doc.paragraphs` por sí solo NO incluye el contenido de
    tablas, así que fichas con formato de tabla (ej. "Cliente N",
    "Paciente N") quedarían casi vacías si solo se leyeran los párrafos.

    Args:
        ruta_o_archivo: ruta de archivo (str/Path) o un objeto tipo
            archivo ya abierto.
        parrafos_por_pagina: cantidad de bloques que forman cada "página"
            simulada, usada solo para poder citar una referencia aproximada.

    Returns:
        Lista de dicts {"page_number": int, "text": str}.
    """
    doc = DocxDocument(ruta_o_archivo)
    bloques: List[str] = []

    def _texto_de_tabla(tabla) -> str:
        """Convierte una tabla en texto plano, una fila por línea,
        con las celdas separadas por ' | ' para preservar la relación
        campo-valor típica de las fichas."""
        lineas = []
        for fila in tabla.rows:
            celdas = [c.text.strip() for c in fila.cells]
            celdas = [c for c in celdas if c]
            if celdas:
                lineas.append(" | ".join(celdas))
        return "\n".join(lineas)

    # Recorre el XML del cuerpo del documento en orden, para intercalar
    # párrafos y tablas tal como aparecen visualmente en el Word.
    cuerpo = doc.element.body
    mapa_parrafos = {p._element: p for p in doc.paragraphs}
    mapa_tablas = {t._element: t for t in doc.tables}

    for elemento in cuerpo.iterchildren():
        if elemento in mapa_parrafos:
            texto = mapa_parrafos[elemento].text.strip()
            if texto:
                bloques.append(texto)
        elif elemento in mapa_tablas:
            texto_tabla = _texto_de_tabla(mapa_tablas[elemento])
            if texto_tabla:
                bloques.append(texto_tabla)

    paginas = []
    for i in range(0, len(bloques), parrafos_por_pagina):
        grupo = bloques[i: i + parrafos_por_pagina]
        texto = "\n".join(grupo)
        if texto.strip():
            paginas.append(
                {"page_number": (i // parrafos_por_pagina) + 1, "text": texto}
            )
    return paginas


def detectar_encabezado_registro(texto_completo: str) -> Optional[re.Pattern]:
    """Detecta AUTOMÁTICAMENTE si el documento está estructurado en fichas
    repetidas (ej. "Cliente 1", "Paciente 2", "Ticket 003", "Empleado N",
    "Producto 45"...) sin asumir ninguna palabra fija de antemano — cada
    empresa nombra sus registros de forma distinta.

    Busca líneas cortas (1-2 palabras) que terminen en un número, y que
    esa MISMA etiqueta se repita al menos 2 veces con números distintos
    a lo largo del documento. Eso es un indicio fuerte de que se trata
    de una serie de fichas/registros, no de texto corrido.

    Returns:
        Un patrón compilado (para usar con re.split, con lookahead) que
        coincide con el inicio de cada ficha detectada; o None si el
        documento no muestra ese patrón (texto corrido normal).
    """
    patron_linea = re.compile(
        r"^[ \t]*([A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ]*(?:[ \t]+[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ]*)?)"
        r"[ \t]*[:#°ºNn.]*[ \t]*(\d{1,6})[ \t]*$",
        re.MULTILINE,
    )

    conteo_por_etiqueta: Dict[str, set] = {}
    for match in patron_linea.finditer(texto_completo):
        etiqueta = match.group(1).strip().lower()
        numero = match.group(2)
        conteo_por_etiqueta.setdefault(etiqueta, set()).add(numero)

    # Solo cuentan etiquetas con al menos 2 apariciones con NÚMEROS
    # DISTINTOS (una sola vez podría ser una fecha, un total, etc.,
    # no necesariamente el separador real de fichas).
    candidatos = {
        etiqueta: numeros
        for etiqueta, numeros in conteo_por_etiqueta.items()
        if len(numeros) >= 2
    }

    if not candidatos:
        return None

    # Se elige la etiqueta con más repeticiones: la más probable de ser
    # el separador real de fichas del documento.
    mejor_etiqueta = max(candidatos, key=lambda e: len(candidatos[e]))

    return re.compile(
        r"(?=^[ \t]*" + re.escape(mejor_etiqueta) + r"[ \t]*[:#°ºNn.]*[ \t]*\d+\b)",
        re.IGNORECASE | re.MULTILINE,
    )


def dividir_por_registros(
    doc_name: str, paginas: List[Dict[str, Any]], patron_split: re.Pattern
) -> List[Chunk]:
    """Chunking para documentos tipo 'ficha' (Cliente 1, Paciente 2, ...).

    Concatena todas las páginas insertando un marcador invisible entre
    ellas para poder rastrear en qué página(s) cae cada registro, y luego
    divide el texto completo usando el patrón de ficha ya detectado
    (`patron_split`, específico de este documento). Así, un registro que
    el PDF/Word cortó justo en un salto de página queda igualmente
    completo en un solo chunk, citando el rango real (ej. "páginas 1-2").
    """
    marcador = "\x00PAGE:{}\x00"
    partes = []
    for pagina in paginas:
        partes.append(marcador.format(pagina["page_number"]))
        partes.append(pagina["text"])
    texto_completo = "\n".join(partes)

    patron_marcador = re.compile(r"\x00PAGE:(\d+)\x00")

    bloques = patron_split.split(texto_completo)

    chunks: List[Chunk] = []
    pagina_actual = paginas[0]["page_number"]
    idx_chunk = 0

    for bloque in bloques:
        paginas_en_bloque = [int(p) for p in patron_marcador.findall(bloque)]
        texto_limpio = patron_marcador.sub("", bloque).strip()

        # La página de INICIO del bloque es la que estaba vigente justo
        # antes de entrar a este bloque (heredada del bloque anterior),
        # no la del primer marcador que aparezca dentro de él — de lo
        # contrario, un registro que empieza en la página 1 y solo cruza
        # a la página 2 a mitad de camino quedaría mal etiquetado como
        # si empezara en la página 2.
        pagina_inicio = pagina_actual

        if paginas_en_bloque:
            pagina_fin = paginas_en_bloque[-1]
            pagina_actual = pagina_fin
        else:
            pagina_fin = pagina_actual

        if not texto_limpio:
            continue

        chunks.append(
            Chunk(
                doc_name=doc_name,
                page_number=pagina_inicio,
                page_number_fin=pagina_fin,
                chunk_index=idx_chunk,
                text=texto_limpio,
            )
        )
        idx_chunk += 1

    return chunks


def construir_indice(chunks: List[Chunk]) -> IndiceDocumental:
    """Construye el índice BM25 a partir de la lista de chunks."""
    if not chunks:
        return IndiceDocumental(chunks=[], bm25=None)

    corpus_tokenizado = [tokenizar(c.text) for c in chunks]
    bm25 = BM25Okapi(corpus_tokenizado)
    return IndiceDocumental(chunks=chunks, bm25=bm25)


# =============================================================================
# MÓDULO DE BÚSQUEDA (RETRIEVAL)
# =============================================================================

_PALABRAS_CLAVE_AGREGACION = (
    "todos", "todas", "cada", "lista", "listado", "listame", "lístame",
    "cuales", "cuáles", "cuantos", "cuántos", "cuantas", "cuántas",
    "enumera", "enumerame", "enumérame",
)


def _es_pregunta_de_listado(pregunta: str) -> bool:
    """Detecta si la pregunta pide un listado/totalidad de registros
    (en vez de apuntar a un registro puntual), para poder ampliar la
    cantidad de fragmentos recuperados y no perder resultados relevantes
    frente a coincidencias léxicas ruidosas (ej. el título del documento)."""
    tokens = set(tokenizar(pregunta))
    return any(palabra in tokens for palabra in _PALABRAS_CLAVE_AGREGACION)


def determinar_top_k(pregunta: str, total_chunks: int) -> int:
    """Decide cuántos fragmentos pedir a BM25 según el tipo de pregunta.

    Si la pregunta parece pedir un listado o totalidad de registros
    ("todos los pacientes de X", "cuáles clientes tienen Y"), se usa un
    top_k más generoso para no perder registros relevantes cuando hay
    fragmentos ruidosos (como el título del documento) compitiendo por
    los primeros lugares del ranking. Nunca se pide más fragmentos que
    los que existen en el índice.
    """
    if _es_pregunta_de_listado(pregunta):
        return min(total_chunks, TOP_K_FRAGMENTOS_AGREGACION)
    return min(total_chunks, TOP_K_FRAGMENTOS)


def buscar_contexto_relevante(
    pregunta: str,
    indice: IndiceDocumental,
    top_k: int = TOP_K_FRAGMENTOS,
) -> List[Chunk]:
    """Busca los `top_k` chunks más relevantes para la pregunta usando BM25.

    Args:
        pregunta: pregunta del usuario en lenguaje natural.
        indice: índice documental ya construido.
        top_k: cantidad de fragmentos a recuperar.

    Returns:
        Lista de Chunks ordenados de mayor a menor relevancia. Puede
        devolver una lista vacía si el índice está vacío o no hay
        coincidencias con score positivo.
    """
    if indice.esta_vacio() or indice.bm25 is None:
        return []

    tokens_pregunta = tokenizar(pregunta)
    if not tokens_pregunta:
        return []

    scores = indice.bm25.get_scores(tokens_pregunta)

    # BM25Okapi puede asignar scores cero o negativos cuando el corpus es
    # muy pequeño (por ejemplo, un único PDF por caso). En ese escenario,
    # descartar todo score <= 0 deja el chat sin contexto aunque sí existan
    # términos compartidos. Conservamos el ranking BM25 cuando hay scores
    # positivos y usamos solapamiento léxico como fallback para corpus chicos.
    resultados = nlargest(
        top_k,
        ((score, position, chunk) for position, (chunk, score) in
         enumerate(zip(indice.chunks, scores, strict=True)) if score > 0),
    )
    if resultados:
        return [chunk for _, _, chunk in resultados]

    palabras_vacias = {
        "a", "al", "algo", "como", "con", "cual", "cuales", "cuando", "de",
        "del", "desde", "donde", "el", "ella", "en", "es", "esta", "este",
        "la", "las", "lo", "los", "me", "mi", "o", "para", "por", "que",
        "se", "su", "sus", "un", "una", "y",
    }
    terminos_consulta = set(tokens_pregunta) - palabras_vacias
    if not terminos_consulta:
        terminos_consulta = set(tokens_pregunta)

    coincidencias = []
    for chunk in indice.chunks:
        terminos_chunk = set(tokenizar(chunk.text))
        cobertura = len(terminos_consulta & terminos_chunk)
        if cobertura:
            coincidencias.append((chunk, cobertura))
    coincidencias.sort(key=lambda item: item[1], reverse=True)
    return [chunk for chunk, _ in coincidencias[:top_k]]


# =============================================================================
# MÓDULO DE CONSULTA AL LLM (GENERATION)
# =============================================================================

PROMPT_SISTEMA = prompts.PROMPT_SISTEMA   # texto en vexa/rag/prompts.py


def construir_prompt(pregunta: str, fragmentos: List[Chunk]) -> str:
    """Ensambla el prompt final combinando el contexto recuperado con la
    pregunta del usuario."""
    contexto = "\n\n".join(
        prompts.PLANTILLA_FRAGMENTO.format(numero=i, fuente=chunk.fuente, texto=chunk.text)
        for i, chunk in enumerate(fragmentos, start=1))
    return prompts.PLANTILLA_PREGUNTA.format(contexto=contexto, pregunta=pregunta)
