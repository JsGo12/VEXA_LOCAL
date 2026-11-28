"""Pruebas unitarias de la extracción de texto por formato (sin OCR)."""
from vexa.rag import formats


def test_decoding_handles_bom_and_windows_encoding():
    assert formats._decodificar(b"\xef\xbb\xbfhola") == "hola"
    assert formats._decodificar("año".encode("cp1252")) == "año"
    assert formats._decodificar("señor".encode()) == "señor"


def test_rows_become_labelled_records():
    paginas = formats._filas_a_paginas([["Nombre", "RUT"], ["Ana", "1-9"], ["", ""]], "")
    assert paginas == [{"page_number": 1, "text": "Nombre: Ana | RUT: 1-9"}]
    assert formats._filas_a_paginas([], "") == []


def test_missing_headers_and_extra_cells_get_column_names():
    paginas = formats._filas_a_paginas([["", "Ciudad"], ["Ana", "Talca", "extra"]], "Hoja 1")
    assert paginas[0]["text"] == "Hoja 1 | Col1: Ana | Ciudad: Talca | Col3: extra"


def test_rows_are_paged():
    filas = [["n"]] + [[str(i)] for i in range(formats.FILAS_POR_PAGINA + 1)]
    paginas = formats._filas_a_paginas(filas, "", pagina0=3)
    assert [p["page_number"] for p in paginas] == [3, 4]
