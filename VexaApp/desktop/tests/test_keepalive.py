import numpy as np

import rag_core
import rag_hybrid
import rag_stages


class RecordingOllama:
    def __init__(self):
        self.keep_alive_values = []

    def chat(self, **kwargs):
        self.keep_alive_values.append(kwargs["keep_alive"])
        if kwargs.get("stream"):
            return iter([{"message": {"content": "respuesta"}}])
        return {"message": {"content": "pregunta independiente"}}

    def embed(self, **kwargs):
        self.keep_alive_values.append(kwargs["keep_alive"])
        return {"embeddings": [[1.0, 0.0] for _ in kwargs["input"]]}


def test_all_ollama_calls_use_the_shared_keep_alive_setting(monkeypatch):
    client = RecordingOllama()
    monkeypatch.setattr(rag_core, "OLLAMA_KEEP_ALIVE", "17s")
    monkeypatch.setattr(rag_core, "cliente_ollama", lambda host=None: client)
    chunk = rag_core.Chunk("contrato.pdf", 1, 0, "La renta mensual es de 450.000 pesos.")
    index = rag_hybrid._armar([chunk], None, set(), rag_hybrid.EMBED_MODEL)

    assert rag_core.consultar_llm("¿Cuál es la renta?", [chunk], "modelo") == "pregunta independiente"
    assert list(rag_core.consultar_llm_stream("¿Cuál es la renta?", [chunk], "modelo")) == ["respuesta"]
    assert rag_hybrid._embed(["texto"], "embeddings").shape == (1, 2)
    assert rag_hybrid.reformular_pregunta(
        "¿y su monto?", [{"role": "user", "content": "¿Qué dice el contrato?"}], "modelo",
    ) == "pregunta independiente"
    assert list(rag_hybrid.consultar_stream("¿Cuál es la renta?", [chunk], [], "modelo")) == ["respuesta"]
    rag_hybrid.precargar_modelo("modelo")
    assert rag_stages._llamar("modelo", "sistema", "usuario") == "pregunta independiente"

    events = list(rag_stages.responder_por_etapas(
        "¿Cuál es la renta?", index, "modelo", {}, 4500, chunks=[chunk],
    ))
    assert any(event["type"] == "delta" and event["text"] == "respuesta" for event in events)
    assert client.keep_alive_values
    assert set(client.keep_alive_values) == {"17s"}


def test_precache_is_skipped_when_model_should_unload_immediately(monkeypatch):
    monkeypatch.setattr(rag_core, "OLLAMA_KEEP_ALIVE", "0")
    monkeypatch.setattr(
        rag_core, "cliente_ollama",
        lambda host=None: (_ for _ in ()).throw(AssertionError("no debe cargar el modelo")),
    )

    rag_hybrid.precargar_modelo("modelo")
