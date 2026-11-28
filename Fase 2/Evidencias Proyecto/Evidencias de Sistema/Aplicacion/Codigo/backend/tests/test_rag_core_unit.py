"""Pruebas unitarias del núcleo RAG: tokenización, fichas, BM25 y prompt."""
from vexa.rag import core


def _chunk(text, page=1, index=0, doc="a.txt", fin=None):
    return core.Chunk(doc_name=doc, page_number=page, chunk_index=index, text=text, page_number_fin=fin)


def test_tokenizer_lowercases_and_removes_accents():
    assert core.tokenizar("Árbol ÑANDÚ, cláusula 5") == ["arbol", "nandu", "clausula", "5"]
    assert core.tokenizar("¿?¡!") == []


def test_chunk_source_label_for_one_or_more_pages():
    assert _chunk("x").fuente == "a.txt — página 1"
    assert _chunk("x", page=2, fin=2).fuente == "a.txt — página 2"
    assert _chunk("x", page=1, fin=3).fuente == "a.txt — páginas 1-3"
