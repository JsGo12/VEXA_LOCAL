"""Pruebas unitarias de la búsqueda híbrida: cláusulas, vecinos, contexto y memoria."""
from vexa.rag import hybrid
from vexa.rag.core import Chunk


def _chunk(index, text="texto", doc="a.txt"):
    return Chunk(doc_name=doc, page_number=1, chunk_index=index, text=text)


def test_units_split_on_blank_lines_and_clauses():
    texto = "PRIMERO: uno\ncontinúa\n\nSEGUNDO: dos\nCLÁUSULA TERCERA: tres"
    assert hybrid._unidades(texto) == ["PRIMERO: uno continúa", "SEGUNDO: dos", "CLÁUSULA TERCERA: tres"]


def test_long_units_are_cut_only_between_sentences():
    assert hybrid._partir_largo("corto", 100) == ["corto"]
    texto = "Primera oración larga. Segunda oración larga. Tercera oración larga."
    piezas = hybrid._partir_largo(texto, 30)
    assert len(piezas) == 3
    assert all(p.endswith(".") for p in piezas)
    assert " ".join(piezas) == texto
