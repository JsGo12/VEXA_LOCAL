"""Pruebas unitarias de las respuestas por etapas (map-reduce)."""
from vexa.rag import stages
from vexa.rag.core import Chunk


def _chunk(index, text="texto", doc="a.txt"):
    return Chunk(doc_name=doc, page_number=index + 1, chunk_index=index, text=text)


def test_totality_questions_are_detected():
    assert stages.es_totalidad("Lista todos los plazos del expediente")
    assert stages.es_totalidad("¿Cuántas audiencias hay en total?")
    assert not stages.es_totalidad("¿Cuál es el plazo de la apelación?")
