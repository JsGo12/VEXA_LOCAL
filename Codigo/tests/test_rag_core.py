"""Pruebas unitarias del motor RAG (no requieren Ollama en ejecución)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import rag_core as core


def test_tokenizar_ignora_tildes_y_mayusculas():
    assert core._tokenizar("Canción ÁRBOL, año!") == ["cancion", "arbol", "ano"]


def test_dividir_en_chunks_vacio():
    assert core.dividir_en_chunks("doc.pdf", []) == []


def test_chunks_conservan_metadata_de_pagina():
    texto = " ".join(f"palabra{i}" for i in range(500))
    chunks = core.dividir_en_chunks("informe.pdf", [{"page_number": 3, "text": texto}])
    assert len(chunks) > 1
    assert all(c.page_number == 3 and c.doc_name == "informe.pdf" for c in chunks)


def test_fuente_una_pagina_y_rango():
    c = core.Chunk("a.pdf", 2, 0, "x")
    assert c.fuente == "a.pdf — página 2"
    c.page_number_fin = 4
    assert c.fuente == "a.pdf — páginas 2-4"


def test_top_k_listado_vs_puntual():
    assert core.determinar_top_k("dame el detalle del cliente 5", 50) == core.TOP_K_FRAGMENTOS
    assert core.determinar_top_k("todos los clientes de Santiago", 50) == core.TOP_K_FRAGMENTOS_AGREGACION
    assert core.determinar_top_k("todos los clientes", 2) == 2


def test_indice_vacio():
    assert core.IndiceDocumental().esta_vacio()
