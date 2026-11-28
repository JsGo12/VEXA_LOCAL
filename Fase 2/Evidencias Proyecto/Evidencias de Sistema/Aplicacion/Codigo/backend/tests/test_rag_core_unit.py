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


def test_listing_questions_use_a_larger_top_k():
    assert core._es_pregunta_de_listado("¿Cuáles son todos los clientes?")
    assert not core._es_pregunta_de_listado("¿Cuál es el teléfono de Ana?")
    assert core.determinar_top_k("lista de clientes", 100) == core.TOP_K_FRAGMENTOS_AGREGACION
    assert core.determinar_top_k("teléfono de Ana", 100) == core.TOP_K_FRAGMENTOS


def test_top_k_never_exceeds_available_chunks():
    assert core.determinar_top_k("lista de clientes", 2) == 2
    assert core.determinar_top_k("teléfono", 1) == 1
    assert core.determinar_top_k("teléfono", 0) == 0


def test_record_header_is_detected_only_when_repeated():
    fichas = "Cliente 1\nNombre: Ana\nCliente 2\nNombre: Luis\n"
    assert core.detectar_encabezado_registro(fichas) is not None
    assert core.detectar_encabezado_registro("Este contrato se firma en Santiago.") is None
    assert core.detectar_encabezado_registro("Total 1500\nResumen del caso") is None


def test_records_crossing_a_page_break_stay_together():
    paginas = [{"page_number": 1, "text": "Cliente 1\nNombre: Ana\nCliente 2\nNombre:"},
               {"page_number": 2, "text": "Luis\nCliente 3\nNombre: Eva"}]
    patron = core.detectar_encabezado_registro("\n".join(p["text"] for p in paginas))
    chunks = core.dividir_por_registros("fichas.pdf", paginas, patron)
    assert [(c.page_number, c.page_number_fin) for c in chunks] == [(1, 1), (1, 2), (2, 2)]
    assert "Luis" in chunks[1].text
    assert [c.chunk_index for c in chunks] == [0, 1, 2]


def test_empty_index_returns_no_context():
    indice = core.construir_indice([])
    assert indice.esta_vacio() and indice.bm25 is None
    assert core.buscar_contexto_relevante("arriendo", indice) == []


def test_single_chunk_corpus_uses_lexical_fallback():
    chunk = _chunk("Contrato de arriendo de oficina en Talca")
    indice = core.construir_indice([chunk])
    assert core.buscar_contexto_relevante("¿Cuánto dura el arriendo?", indice) == [chunk]
    assert core.buscar_contexto_relevante("¿?", indice) == []


def test_bm25_ranks_the_matching_chunk_first():
    chunks = [_chunk("El arrendatario paga la renta mensual", index=0),
              _chunk("La garantía es de un mes de renta", index=1),
              _chunk("El inmueble queda en Valparaíso", index=2),
              _chunk("Las partes fijan domicilio en Santiago", index=3)]
    indice = core.construir_indice(chunks)
    assert core.buscar_contexto_relevante("¿Dónde queda el inmueble?", indice, top_k=1) == [chunks[2]]
