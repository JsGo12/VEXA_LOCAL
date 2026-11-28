"""El chat tiene prioridad sobre el resumen automático y los resúmenes se generan de a uno."""
import threading
import time

from vexa.rag import stages as rag_stages
from vexa.services import llm_priority
from vexa.services.indexing import CaseIndexer


def test_background_waits_while_someone_is_chatting():
    released = []

    def background():
        llm_priority.esperar_turno(grace=0.05, max_wait=5)
        released.append(time.monotonic())

    with llm_priority.interactive():
        worker = threading.Thread(target=background)
        worker.start()
        time.sleep(0.3)
        assert not released and llm_priority.interactive_active() == 1      # sigue esperando
        chat_ended = time.monotonic()
    worker.join(timeout=5)
    assert released and released[0] >= chat_ended                           # retoma al terminar el chat


def test_background_does_not_wait_forever():
    with llm_priority.interactive():
        started = time.monotonic()
        assert llm_priority.esperar_turno(grace=0.01, max_wait=0.2) is False
        assert time.monotonic() - started < 2


def test_summary_yields_before_each_model_call(monkeypatch):
    calls = []
    monkeypatch.setattr(rag_stages, "_llamar", lambda *a, **k: calls.append("modelo") or "resumen")
    monkeypatch.setattr(rag_stages, "lotes", lambda chunks: [["a"], ["b"]])
    monkeypatch.setattr(rag_stages, "_texto", lambda g: "texto")

    class Indice:
        chunks = ["x"]

    rag_stages.resumir_indice(Indice(), "modelo", antes_de_llamar=lambda: calls.append("turno"))
    assert calls == ["turno", "modelo", "turno", "modelo", "turno", "modelo"]   # 2 lotes + resumen final


def test_summaries_run_one_at_a_time_and_keep_latest_version(tmp_path, monkeypatch):
    indexer = CaseIndexer(tmp_path / "x.db")
    running, peak, done = [0], [0], []
    gate = threading.Event()

    def fake(case_id, index, signature):
        running[0] += 1
        peak[0] = max(peak[0], running[0])
        gate.wait(timeout=5)
        done.append((case_id, signature))
        running[0] -= 1

    monkeypatch.setattr(indexer, "_generar_resumen", fake)
    indexer.queue_summary(1, "idx", "sig-1")
    time.sleep(0.1)                                   # el caso 1 ya está en proceso
    indexer.queue_summary(2, "idx", "sig-a")
    indexer.queue_summary(2, "idx", "sig-b")          # reemplaza a la versión anterior del caso 2
    indexer.queue_summary(3, "idx", "sig-x")
    gate.set()
    deadline = time.monotonic() + 5
    while len(done) < 3 and time.monotonic() < deadline:
        time.sleep(0.02)
    assert done == [(1, "sig-1"), (2, "sig-b"), (3, "sig-x")]
    assert peak[0] == 1 and indexer.summaries_pending() == 0
