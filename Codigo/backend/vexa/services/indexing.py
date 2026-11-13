"""Índices RAG por expediente: caché en memoria, indexación en segundo plano y resúmenes.

Seguridad de cachés:
- La clave del índice es (case_id, firma), y la firma incluye la ruta, el SHA, el tamaño y la fecha de
  CADA documento incluido. Un usuario con un conjunto distinto de documentos autorizados obtiene
  otra firma y, por lo tanto, otro índice: nunca se reutiliza un índice con documentos que no puede ver.
- La clave de respuestas incluye además el id del usuario.
- El índice de fondo y el resumen automático se construyen solo con documentos NO restringidos.
"""
from __future__ import annotations

import hashlib
import logging
from collections import OrderedDict
from contextlib import contextmanager
from pathlib import Path
from threading import Lock, RLock, Thread
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from vexa.database import connect, store
from vexa.permissions import policy
from vexa.rag import hybrid as rag_hybrid
from vexa.rag import model_select
from vexa.rag import stages as rag_stages

LOGGER = logging.getLogger(__name__)
Signature = Tuple[Tuple[str, Optional[str], int, int], ...]


def document_paths(rows: Sequence) -> Tuple[List[str], Dict[str, str]]:
    """(rutas existentes, {ruta: nombre original}) de una lista de filas de documents."""
    rows = [r for r in rows if Path(r["stored_path"]).is_file()]
    return [r["stored_path"] for r in rows], {r["stored_path"]: r["original_name"] for r in rows}


class CaseIndexer:
    MAX_CACHED_INDEXES = 8
    MAX_CACHED_ANSWERS = 128

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self._index_cache: "OrderedDict[tuple, rag_hybrid.IndiceHibrido]" = OrderedDict()
        self._answer_cache: "OrderedDict[tuple, tuple]" = OrderedDict()
        self._rag_cache_lock = RLock()
        self._build_locks: Dict[int, list] = {}
        self._build_locks_guard = Lock()
        self._jobs: Dict[int, dict] = {}
        self._partial: Dict[int, tuple] = {}
        self._rerun: set = set()
        self._jobs_lock = RLock()

    # ----------------------------------------------------------------- utilidades
    @contextmanager
    def _lock_build_caso(self, case_id: int):
        """Serializa la construcción del mismo caso sin bloquear indexaciones de otros casos."""
        with self._build_locks_guard:
            entry = self._build_locks.get(case_id)
            if entry is None:
                entry = [Lock(), 0]
                self._build_locks[case_id] = entry
            entry[1] += 1
        lock = entry[0]
        acquired = False
        try:
            lock.acquire()
            acquired = True
            yield
        finally:
            if acquired:
                lock.release()
            with self._build_locks_guard:
                entry[1] -= 1
                if entry[1] == 0 and self._build_locks.get(case_id) is entry:
                    del self._build_locks[case_id]

    def background_documents(self, case_id: int) -> Tuple[List[str], Dict[str, str]]:
        with connect(self.db_path) as db:
            return document_paths(policy.unrestricted_documents(db, case_id))

    def signature(self, paths: Sequence[str]) -> Signature:
        """Revisión de cada documento: ruta, SHA persistido, tamaño y fecha de modificación."""
        if not paths:
            return ()
        with connect(self.db_path) as db:
            marks = ",".join("?" for _ in paths)
            rows = db.execute(f"SELECT stored_path, sha256 FROM documents WHERE stored_path IN ({marks})",
                              list(paths)).fetchall()
        hashes = {row["stored_path"]: row["sha256"] for row in rows}
        return tuple((path, hashes.get(path), stat.st_size, stat.st_mtime_ns)
                     for path in paths for stat in (Path(path).stat(),))

    # --------------------------------------------------------------------- índice
    def get_index(self, case_id: int, paths: List[str], names: Optional[Dict[str, str]] = None,
                  progreso: Optional[Callable[[float, str], None]] = None,
                  parcial: Optional[Callable] = None) -> Tuple[rag_hybrid.IndiceHibrido, Signature, bool]:
        """Índice híbrido de exactamente `paths`. El armado ocurre fuera del lock de cachés."""
        signature = self.signature(paths)
        cache_key = (case_id, signature)
        with self._lock_build_caso(case_id):
            with self._rag_cache_lock:
                index = self._index_cache.get(cache_key)
                if index is not None:
                    self._index_cache.move_to_end(cache_key)
                    return index, signature, True
            if names is None:
                with connect(self.db_path) as db:
                    rows = db.execute("SELECT original_name, stored_path FROM documents WHERE case_id = ?",
                                      (case_id,)).fetchall()
                names = {r["stored_path"]: r["original_name"] for r in rows}
            index = rag_hybrid.construir_indice_hibrido(paths, db_path=self.db_path, progreso=progreso,
                                                        nombres=names, parcial=parcial)
            current = {path: (sha, size, mtime) for path, sha, size, mtime in signature}
            with self._rag_cache_lock:
                # Se descartan versiones obsoletas del mismo conjunto de documentos del caso.
                for old_key in [k for k in self._index_cache if k[0] == case_id and
                                {p for p, *_ in k[1]} == set(current) and k[1] != signature]:
                    del self._index_cache[old_key]
                self._index_cache[cache_key] = index
                while len(self._index_cache) > self.MAX_CACHED_INDEXES:
                    self._index_cache.popitem(last=False)
                self._drop_stale_answers()
            return index, signature, False

    def _drop_stale_answers(self) -> None:
        live = set(self._index_cache)
        for key in [k for k in self._answer_cache if (k[0], k[1]) not in live]:
            del self._answer_cache[key]

    def invalidate_case(self, case_id: int) -> None:
        with self._rag_cache_lock:
            for key in [k for k in self._index_cache if k[0] == case_id]:
                del self._index_cache[key]
            for key in [k for k in self._answer_cache if k[0] == case_id]:
                del self._answer_cache[key]

    # --------------------------------------------------------------- respuestas
    def cached_answer(self, key: tuple):
        with self._rag_cache_lock:
            value = self._answer_cache.get(key)
            if value is not None:
                self._answer_cache.move_to_end(key)
            return value

    def store_answer(self, key: tuple, value: tuple) -> None:
        with self._rag_cache_lock:
            if (key[0], key[1]) not in self._index_cache:
                return
            self._answer_cache[key] = value
            self._answer_cache.move_to_end(key)
            while len(self._answer_cache) > self.MAX_CACHED_ANSWERS:
                self._answer_cache.popitem(last=False)

    # ---------------------------------------------------------- trabajos de fondo
    def job(self, case_id: int) -> dict:
        with self._jobs_lock:
            return dict(self._jobs.get(case_id, {"state": "idle", "progress": 0.0, "message": ""}))

    def partial(self, case_id: int):
        with self._jobs_lock:
            return self._jobs.get(case_id), self._partial.get(case_id)

    def schedule(self, case_id: int) -> None:
        Thread(target=self.preload, args=(case_id,), daemon=True).start()

    def _generar_resumen(self, case_id: int, index, signature) -> None:
        sig = hashlib.sha1(repr(signature).encode()).hexdigest()
        previo = store.get_summary(self.db_path, case_id)
        if previo and previo[0] == sig:
            return
        try:
            perfil = model_select.perfil_actual()
            texto = rag_stages.resumir_indice(index, perfil.modelo, opciones=perfil.opciones)
            if texto:
                store.save_summary(self.db_path, case_id, sig, texto)
        except Exception:
            LOGGER.warning("No se pudo generar el resumen automático del caso %s", case_id)

    def preload(self, case_id: int) -> None:
        """Indexa en segundo plano los documentos no restringidos. Si llegan archivos nuevos
        durante el proceso, vuelve a indexar hasta 3 veces."""
        with self._jobs_lock:
            job = self._jobs.get(case_id)
            if job and job["state"] == "running":
                self._rerun.add(case_id)
                return
            self._jobs[case_id] = {"state": "running", "progress": 0.0, "message": "Iniciando"}
            self._rerun.discard(case_id)
            self._partial.pop(case_id, None)

        def avance(fraccion, mensaje):
            with self._jobs_lock:
                self._jobs[case_id].update(progress=round(fraccion, 3), message=mensaje)

        def parcial(indice, hechos, total):
            with self._jobs_lock:
                self._partial[case_id] = (indice, hechos, total, tuple(paths))

        try:
            resultado = None
            for _ in range(3):
                paths, names = self.background_documents(case_id)
                if not paths:
                    with self._jobs_lock:
                        self._jobs[case_id] = {"state": "error", "progress": 0.0,
                                               "message": "No hay documentos disponibles para indexar"}
                        self._partial.pop(case_id, None)
                    return
                resultado = self.get_index(case_id, paths, names, progreso=avance, parcial=parcial)
                with self._jobs_lock:
                    if case_id in self._rerun:
                        self._rerun.discard(case_id)
                        continue
                break
            with self._jobs_lock:
                if not resultado or resultado[0].esta_vacio():
                    errors = getattr(resultado[0], "errores", []) if resultado else []
                    message = "No se pudo extraer texto de los documentos"
                    if errors:
                        message += ": " + "; ".join(errors[:3])
                    self._jobs[case_id] = {"state": "error", "progress": 1.0, "message": message}
                else:
                    index = resultado[0]
                    message = "Listo"
                    if index.errores:
                        message = (f"Listo con {len(index.errores)} archivo(s) omitido(s): "
                                   + "; ".join(index.errores[:3]))
                    self._jobs[case_id] = {"state": "done", "progress": 1.0, "message": message}
                self._partial.pop(case_id, None)
            if resultado:
                index, signature, _hit = resultado
                perfil = model_select.perfil_actual()
                Thread(target=rag_hybrid.precargar_modelo, args=(perfil.modelo,), daemon=True).start()
                Thread(target=self._generar_resumen, args=(case_id, index, signature), daemon=True).start()
        except Exception:
            LOGGER.exception("No se pudo precargar el índice del caso %s", case_id)
            with self._jobs_lock:
                self._jobs[case_id] = {"state": "error", "progress": 0.0,
                                       "message": "No se pudieron leer los documentos"}
                self._partial.pop(case_id, None)
