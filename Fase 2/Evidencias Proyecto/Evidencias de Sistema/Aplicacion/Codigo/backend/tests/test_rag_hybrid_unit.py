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


def test_chunker_handles_empty_and_prose_documents():
    assert hybrid.chunkear("a.txt", []) == ([], False)
    paginas = [{"page_number": 1, "text": "El contrato rige desde marzo."},
               {"page_number": 2, "text": "Las partes firman en Talca."}]
    chunks, ficha = hybrid.chunkear("a.txt", paginas)
    assert ficha is False
    assert chunks[0].page_number == 1 and chunks[-1].page_number_fin == 2


def test_chunker_keeps_records_whole():
    paginas = [{"page_number": 1, "text": "Cliente 1\nNombre: Ana\nCliente 2\nNombre: Luis"}]
    chunks, ficha = hybrid.chunkear("fichas.txt", paginas)
    assert ficha is True
    assert [c.text.splitlines()[0] for c in chunks] == ["Cliente 1", "Cliente 2"]


def test_ranking_drops_non_positive_scores():
    import numpy as np
    assert hybrid._ranking(np.array([0.5, 0.0, 2.0, -1.0]), 3) == [2, 0]
    assert hybrid._ranking(np.array([0.0, -0.1]), 5) == []


def test_neighbours_are_added_except_for_records():
    chunks = [_chunk(0), _chunk(1), _chunk(2), _chunk(3)]
    indice = hybrid._armar(chunks, None, set(), "modelo")
    assert [c.chunk_index for c in hybrid.con_vecinos([chunks[1]], indice)] == [0, 1, 2]
    fichas = hybrid._armar(chunks, None, {"a.txt"}, "modelo")
    assert hybrid.con_vecinos([chunks[1]], fichas) == [chunks[1]]


def test_neighbours_are_not_duplicated():
    chunks = [_chunk(0), _chunk(1), _chunk(2)]
    indice = hybrid._armar(chunks, None, set(), "modelo")
    vecinos = hybrid.con_vecinos([chunks[0], chunks[1]], indice)
    assert [c.chunk_index for c in vecinos] == [0, 1, 2]


def test_context_limit_prioritises_search_hits():
    acierto = _chunk(1, "a" * 3000)
    vecino = _chunk(0, "b" * 3000)
    assert hybrid.limitar_contexto([vecino, acierto], [acierto], maximo=4500) == [acierto]
    assert hybrid.limitar_contexto([vecino, acierto], [acierto], maximo=7000) == [vecino, acierto]
