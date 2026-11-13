"""RAG transversal de la firma: recuperación sobre VARIOS expedientes ya autorizados.

Este módulo no decide permisos: recibe solo los documentos que `permissions.policy` autorizó para el
usuario y reutiliza el motor híbrido existente (BM25 + embeddings, caché de fragmentos en SQLite).
Cada fragmento conserva el expediente, el documento y las páginas de origen.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from vexa.rag import core as rag_core
from vexa.rag import hybrid as rag_hybrid
from vexa.rag.core import Chunk

MAX_CASE_CARDS = 5
CARD_MAX_CHARS = 450

PROMPT_FIRMA = rag_hybrid.PROMPT_SISTEMA + (
    "- Los fragmentos provienen de DISTINTOS expedientes; la etiqueta de la fuente indica el expediente.\n"
    "- Indica siempre a qué expediente corresponde cada dato y no mezcles datos de expedientes distintos.\n"
    "- Las 'Fichas de expediente' son metadatos internos (responsable, fecha límite, resumen).\n"
)


@dataclass(frozen=True)
class AuthorizedDocument:
    document_id: int
    case_id: int
    case_label: str
    original_name: str
    stored_path: str

    @property
    def label(self) -> str:
        return f"{self.case_label} › {self.original_name} (doc {self.document_id})"


@dataclass(frozen=True)
class CaseCard:
    case_id: int
    label: str
    text: str

    @property
    def doc_name(self) -> str:
        return f"Ficha de expediente {self.label}"

    def chunk(self) -> Chunk:
        return Chunk(doc_name=self.doc_name, page_number=1, chunk_index=0, text=self.text[:CARD_MAX_CHARS])


def build_index(documents: Sequence[AuthorizedDocument], db_path=None, progreso=None) -> rag_hybrid.IndiceHibrido:
    names = {d.stored_path: d.label for d in documents}
    return rag_hybrid.construir_indice_hibrido([d.stored_path for d in documents], db_path=db_path,
                                               progreso=progreso, nombres=names)


def retrieve(question: str, index: rag_hybrid.IndiceHibrido, cards: Sequence[CaseCard],
             documents: Sequence[AuthorizedDocument], max_chars: int) -> List[Chunk]:
    """Fragmentos relevantes (con vecinos) + fichas de los expedientes involucrados, dentro del presupuesto."""
    fragments: List[Chunk] = []
    if not index.esta_vacio():
        top_k = max(6, rag_core.determinar_top_k(question, len(index.chunks)))
        hits = rag_hybrid.buscar_hibrido(question, index, top_k=top_k)
        fragments = rag_hybrid.limitar_contexto(rag_hybrid.con_vecinos(hits, index), hits, max_chars)

    by_label = {d.label: d.case_id for d in documents}
    involved = list(dict.fromkeys(by_label[f.doc_name] for f in fragments if f.doc_name in by_label))
    tokens = {t for t in rag_core._tokenizar(question) if len(t) >= 4 and t != "caso"}
    for card in cards:   # expedientes nombrados en la pregunta (título o referencia)
        if card.case_id not in involved and tokens & set(rag_core._tokenizar(card.label)):
            involved.append(card.case_id)
    card_map = {c.case_id: c for c in cards}
    budget = max(0, max_chars - sum(len(f.text) for f in fragments))
    extra: List[Chunk] = []
    for case_id in involved[:MAX_CASE_CARDS]:
        chunk = card_map[case_id].chunk() if case_id in card_map else None
        if chunk is not None and (len(chunk.text) <= budget or not fragments):
            extra.append(chunk)
            budget -= len(chunk.text)
    return extra + fragments


def sources_for(fragments: Sequence[Chunk], documents: Sequence[AuthorizedDocument],
                cards: Sequence[CaseCard]) -> List[Dict]:
    """Referencias verificables: expediente, documento y páginas de cada fragmento usado."""
    docs = {d.label: d for d in documents}
    card_names = {c.doc_name: c for c in cards}
    seen: Dict[Tuple, Dict] = {}
    for f in fragments:
        if f.doc_name in docs:
            d = docs[f.doc_name]
            key = ("document", d.document_id, f.page_number, f.page_number_fin or f.page_number)
            seen.setdefault(key, {
                "source_type": "document", "case_id": d.case_id, "case_label": d.case_label,
                "document_id": d.document_id, "label": d.original_name,
                "page_start": f.page_number, "page_end": f.page_number_fin or f.page_number,
            })
        elif f.doc_name in card_names:
            c = card_names[f.doc_name]
            seen.setdefault(("case", c.case_id), {
                "source_type": "case", "case_id": c.case_id, "case_label": c.label,
                "document_id": None, "label": "Ficha del expediente", "page_start": None, "page_end": None,
            })
    return list(seen.values())


def stream_answer(question: str, fragments: Sequence[Chunk], history: List[dict], model: str,
                  options: Optional[dict] = None):
    return rag_hybrid.consultar_stream(question, list(fragments), history, modelo=model, opciones=options,
                                       sistema=PROMPT_FIRMA)
