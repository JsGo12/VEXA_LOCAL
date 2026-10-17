"""Evaluate VEXA's local retrieval and answer pipeline against a JSON dataset."""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import model_select
import rag_core
import rag_hybrid
import rag_stages

ABSTENTION_PHRASES = (
    "no encontré", "no encontre", "no hay información", "no hay informacion",
    "no cuento con información", "no cuento con informacion", "no aparece en",
)


def load_dataset(dataset_path: Path) -> tuple[dict[str, Any], list[str], dict[str, str]]:
    """Load and validate a dataset; relative document paths use its directory."""
    try:
        data = json.loads(dataset_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"No se pudo leer el conjunto de evaluación: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("documents"), list) or not data["documents"]:
        raise ValueError("El conjunto debe declarar al menos un documento en 'documents'.")
    if not isinstance(data.get("questions"), list) or not data["questions"]:
        raise ValueError("El conjunto debe declarar al menos una pregunta en 'questions'.")

    root = dataset_path.resolve().parent
    paths, names = [], {}
    for document in data["documents"]:
        if not isinstance(document, dict) or not isinstance(document.get("path"), str):
            raise ValueError("Cada documento debe tener una ruta en texto.")
        path = Path(document["path"])
        if not path.is_absolute():
            path = root / path
        path = path.resolve()
        if not path.is_file():
            raise ValueError(f"No se encontró el documento de evaluación: {path}")
        name = str(document.get("name") or path.name).strip()
        if not name:
            raise ValueError("El nombre de cada documento no puede estar vacío.")
        paths.append(str(path))
        names[str(path)] = name

    ids = set()
    for question in data["questions"]:
        if not isinstance(question, dict) or not isinstance(question.get("question"), str):
            raise ValueError("Cada pregunta debe incluir el campo 'question'.")
        if not question["question"].strip():
            raise ValueError("Las preguntas no pueden estar vacías.")
        question_id = str(question.get("id", "")).strip()
        if not question_id or question_id in ids:
            raise ValueError("Cada pregunta debe tener un 'id' único y no vacío.")
        ids.add(question_id)
        for field in ("expected_sources", "expected_terms"):
            values = question.get(field, [])
            if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
                raise ValueError(f"'{field}' debe ser una lista de textos en la pregunta {question_id}.")
        if "expected_no_answer" in question and not isinstance(question["expected_no_answer"], bool):
            raise ValueError(f"'expected_no_answer' debe ser booleano en la pregunta {question_id}.")
    return data, paths, names


def score_result(question: dict[str, Any], answer: str, retrieved_sources: list[str],
                 cited_sources: list[str], elapsed_ms: float) -> dict[str, Any]:
    expected_sources = question.get("expected_sources", [])
    expected_terms = question.get("expected_terms", [])
    retrieved_norm = [source.casefold() for source in retrieved_sources]
    retrieved_found = [
        expected for expected in expected_sources
        if any(expected.casefold() in source for source in retrieved_norm)
    ]
    cited_norm = [source.casefold() for source in cited_sources]
    cited_found = [
        expected for expected in expected_sources
        if any(expected.casefold() in source for source in cited_norm)
    ]
    term_found = [term for term in expected_terms if term.casefold() in answer.casefold()]
    abstained = any(phrase in answer.casefold() for phrase in ABSTENTION_PHRASES)
    expects_no_answer = question.get("expected_no_answer", False)
    return {
        "id": question["id"],
        "question": question["question"],
        "answer": answer,
        "retrieved_sources": retrieved_sources,
        "cited_sources": cited_sources,
        "expected_sources": expected_sources,
        "found_expected_sources": cited_found,
        "retrieved_expected_sources": retrieved_found,
        "retrieval_source_recall": len(retrieved_found) / len(expected_sources) if expected_sources else None,
        "citation_source_recall": len(cited_found) / len(expected_sources) if expected_sources else None,
        "expected_terms": expected_terms,
        "found_expected_terms": term_found,
        "term_coverage": len(term_found) / len(expected_terms) if expected_terms else None,
        "expects_no_answer": expects_no_answer,
        "abstained": abstained,
        "abstention_correct": abstained == expects_no_answer,
        "elapsed_ms": round(elapsed_ms, 1),
    }


def summarize_results(results: list[dict[str, Any]], index_ms: float, index) -> dict[str, Any]:
    retrieval_scores = [r["retrieval_source_recall"] for r in results
                        if r["retrieval_source_recall"] is not None]
    citation_scores = [r["citation_source_recall"] for r in results
                       if r["citation_source_recall"] is not None]
    term_hits = sum(len(r["found_expected_terms"]) for r in results)
    term_total = sum(len(r["expected_terms"]) for r in results)
    elapsed = [r["elapsed_ms"] for r in results]
    return {
        "question_count": len(results),
        "retrieval_source_recall": round(statistics.mean(retrieval_scores), 4) if retrieval_scores else None,
        "citation_source_recall": round(statistics.mean(citation_scores), 4) if citation_scores else None,
        "answer_term_coverage": round(term_hits / term_total, 4) if term_total else None,
        "abstention_accuracy": round(sum(r["abstention_correct"] for r in results) / len(results), 4),
        "mean_query_ms": round(statistics.mean(elapsed), 1) if elapsed else 0,
        "median_query_ms": round(statistics.median(elapsed), 1) if elapsed else 0,
        "index_ms": round(index_ms, 1),
        "chunk_count": len(index.chunks),
        "semantic_search": index.semantico,
        "index_errors": getattr(index, "errores", []),
    }


def _answer_one(question: str, index, model: str, options: dict[str, Any], max_chars: int):
    """Use the same retrieval and answer paths as /api/case/<id>/chat."""
    if rag_stages.es_totalidad(question):
        selected = rag_hybrid.buscar_todos_relevantes(question, index)
        if not selected:
            answer = "No encontré información relacionada en este expediente."
            return answer, [], []
        retrieved = list(dict.fromkeys(chunk.doc_name for chunk in selected))
        answer_parts, cited = [], []
        for event in rag_stages.responder_por_etapas(
            question, index, model, options, max_chars, chunks=selected,
        ):
            if event["type"] == "delta":
                answer_parts.append(event["text"])
            elif event["type"] == "sources":
                cited = event["sources"]
        return "".join(answer_parts), retrieved, cited

    top_k = rag_core.determinar_top_k(question, len(index.chunks))
    hits = rag_hybrid.buscar_hibrido(question, index, top_k=top_k)
    fragments = rag_hybrid.limitar_contexto(
        rag_hybrid.con_vecinos(hits, index), hits, max_chars,
    )
    if not fragments:
        return "No encontré información relevante en los documentos cargados para responder esta pregunta.", [], []
    retrieved = list(dict.fromkeys(chunk.doc_name for chunk in fragments))
    cited = list(dict.fromkeys(chunk.fuente for chunk in fragments))
    answer = "".join(rag_hybrid.consultar_stream(question, fragments, [], model, opciones=options))
    return answer, retrieved, cited


def evaluate(dataset_path: Path, model: str | None = None) -> dict[str, Any]:
    data, paths, names = load_dataset(dataset_path)
    try:
        installed = model_select.instalados_ollama()
    except Exception as exc:
        raise RuntimeError("Ollama no responde en localhost:11434. Inícialo antes de evaluar.") from exc
    profile = (model_select.elegir(installed, None, 0, model) if model
               else model_select.perfil_para(installed))
    if not model_select.modelo_instalado(profile.modelo, installed):
        raise RuntimeError(f"No está instalado el modelo {profile.modelo}; ejecuta 'ollama pull {profile.modelo}'.")

    started = time.perf_counter()
    index = rag_hybrid.construir_indice_hibrido(paths, nombres=names)
    index_ms = (time.perf_counter() - started) * 1000
    results = []
    for question in data["questions"]:
        query_started = time.perf_counter()
        try:
            answer, retrieved, cited = _answer_one(
                question["question"], index, profile.modelo, profile.opciones, profile.max_chars,
            )
            error = None
        except Exception as exc:
            answer, retrieved, cited = "", [], []
            error = f"{type(exc).__name__}: {str(exc).splitlines()[0][:240]}"
        row = score_result(question, answer, retrieved, cited,
                           (time.perf_counter() - query_started) * 1000)
        if error:
            row["error"] = error
        results.append(row)
    return {
        "model": profile.modelo,
        "embedding_model": index.modelo_emb if index.semantico else None,
        "dataset": str(dataset_path.resolve()),
        "summary": summarize_results(results, index_ms, index),
        "results": results,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Evalúa recuperación y respuestas del RAG local de VEXA.")
    parser.add_argument("dataset", type=Path, help="JSON local con documentos y preguntas de prueba")
    parser.add_argument("--model", help="modelo Ollama instalado; por defecto se selecciona según el equipo")
    parser.add_argument("--output", type=Path, help="guardar el resultado JSON en este archivo local")
    args = parser.parse_args(argv)
    try:
        report = evaluate(args.dataset, args.model)
    except (ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")
        print(f"Evaluación guardada en {args.output.resolve()}")
        print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    else:
        print(serialized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
