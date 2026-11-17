import json

import eval_rag


def test_score_result_measures_retrieval_citations_terms_and_abstention():
    question = {
        "id": "renta",
        "question": "¿Monto?",
        "expected_sources": ["contrato.pdf", "anexo.pdf"],
        "expected_terms": ["450.000", "pesos"],
        "expected_no_answer": False,
    }

    result = eval_rag.score_result(
        question,
        "La renta es 450.000 pesos.",
        ["contrato.pdf"],
        ["contrato.pdf — página 1"],
        123.4,
    )

    assert result["retrieval_source_recall"] == 0.5
    assert result["citation_source_recall"] == 0.5
    assert result["term_coverage"] == 1.0
    assert result["abstention_correct"] is True
    assert result["elapsed_ms"] == 123.4


def test_score_result_marks_expected_abstention():
    result = eval_rag.score_result(
        {"id": "ausente", "question": "¿Correo?", "expected_no_answer": True},
        "No encontré información relevante en los documentos.", [], [], 20,
    )

    assert result["abstained"] is True
    assert result["abstention_correct"] is True
    assert result["citation_source_recall"] is None
    assert result["term_coverage"] is None


def test_load_dataset_resolves_relative_documents_and_rejects_duplicate_ids(tmp_path):
    doc = tmp_path / "fixture.txt"
    doc.write_text("Texto de prueba", encoding="utf-8")
    dataset = tmp_path / "dataset.json"
    data = {
        "documents": [{"path": "fixture.txt", "name": "fixture"}],
        "questions": [{"id": "q1", "question": "Consulta"}],
    }
    dataset.write_text(json.dumps(data), encoding="utf-8")

    loaded, paths, names = eval_rag.load_dataset(dataset)
    assert loaded["questions"][0]["id"] == "q1"
    assert paths == [str(doc.resolve())]
    assert names[str(doc.resolve())] == "fixture"

    data["questions"].append({"id": "q1", "question": "Otra consulta"})
    dataset.write_text(json.dumps(data), encoding="utf-8")
    try:
        eval_rag.load_dataset(dataset)
    except ValueError as exc:
        assert "único" in str(exc)
    else:
        raise AssertionError("Los identificadores repetidos debieron rechazarse")


def test_summary_aggregates_query_and_citation_metrics():
    index = type("Index", (), {"chunks": [1, 2], "semantico": False, "errores": []})()
    results = [
        {"retrieval_source_recall": 1.0, "citation_source_recall": 1.0,
         "found_expected_terms": ["a"], "expected_terms": ["a", "b"],
         "abstention_correct": True, "elapsed_ms": 100.0},
        {"retrieval_source_recall": 0.0, "citation_source_recall": 0.0,
         "found_expected_terms": [], "expected_terms": ["c"],
         "abstention_correct": False, "elapsed_ms": 300.0},
    ]

    summary = eval_rag.summarize_results(results, 500, index)

    assert summary["retrieval_source_recall"] == 0.5
    assert summary["citation_source_recall"] == 0.5
    assert summary["answer_term_coverage"] == 0.3333
    assert summary["mean_query_ms"] == 200
    assert summary["median_query_ms"] == 200
