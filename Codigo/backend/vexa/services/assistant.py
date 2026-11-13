"""Asistente IA transversal: material autorizado, caché por usuario y conversaciones propias.

- El material (documentos + fichas) se calcula en cada consulta con `policy.assistant_scope`, así un
  cambio de permisos rige desde la consulta siguiente.
- La caché de índices usa la clave (usuario, firma de los documentos autorizados): no se comparte
  entre usuarios ni sobrevive a un cambio del conjunto autorizado.
- Las conversaciones se guardan en tablas propias (assistant_*), cifradas con el vault, y separadas del
  historial de los chats por expediente (chat_messages).
- Al leer una conversación, las respuestas que citan fuentes que el usuario ya no puede ver se ocultan.
"""
from __future__ import annotations

import json
from collections import OrderedDict
from pathlib import Path
from threading import RLock
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from vexa.database import connect
from vexa.permissions import policy
from vexa.rag import firm
from vexa.security import vault
from vexa.services.indexing import CaseIndexer

REDACTED = ("[Respuesta oculta: cita documentos o expedientes a los que ya no tienes acceso. "
            "Vuelve a preguntar para obtener una respuesta con tu alcance actual.]")
HISTORY_MESSAGES = 6


def case_label(case) -> str:
    return f"{case['reference'] or ('#' + str(case['id']))} · {case['title']}"


def _card(case) -> firm.CaseCard:
    assignee = case["team_name"] and f"equipo {case['team_name']}" or case["assignee_name"] or "sin asignar"
    from vexa.services.cases import STATUS_LABELS
    text = (f"Expediente {case_label(case)}. Responsable: {assignee}. Estado: "
            f"{STATUS_LABELS.get(case['status'], case['status'])} ({case['progress']} % de avance). Fecha límite: "
            f"{case['due_at'].replace('T', ' ')}. Documentos: {case['document_count']}. "
            f"Resumen: {case['summary'] or 'sin resumen'}")
    return firm.CaseCard(case_id=case["id"], label=case_label(case), text=text)


class FirmAssistant:
    MAX_CACHED_INDEXES = 4

    def __init__(self, db_path: Path, indexer: CaseIndexer):
        self.db_path = Path(db_path)
        self.indexer = indexer
        self._cache: "OrderedDict[tuple, object]" = OrderedDict()
        self._lock = RLock()

    # ---------------------------------------------------------------- material
    def authorized_material(self, user, case_filter: Optional[Iterable[int]] = None
                            ) -> Tuple[List[firm.AuthorizedDocument], List[firm.CaseCard], Dict[int, set]]:
        from vexa.services.cases import CASE_LIST_SQL

        with connect(self.db_path) as db:
            scope = policy.assistant_scope(db, user)
            if case_filter is not None:
                wanted = {int(c) for c in case_filter}
                scope = {cid: v for cid, v in scope.items() if cid in wanted}
            if not scope:
                return [], [], {}
            marks = ",".join("?" for _ in scope)
            cases = db.execute(CASE_LIST_SQL + f" WHERE c.id IN ({marks}) ORDER BY c.id", list(scope)).fetchall()
            documents: List[firm.AuthorizedDocument] = []
            for case in cases:
                for doc in policy.visible_documents(db, user, case["id"]):
                    if Path(doc["stored_path"]).is_file():
                        documents.append(firm.AuthorizedDocument(doc["id"], case["id"], case_label(case),
                                                                 doc["original_name"], doc["stored_path"]))
        return documents, [_card(c) for c in cases], scope

    def index_for(self, user_id: int, documents: Sequence[firm.AuthorizedDocument], progreso=None):
        signature = self.indexer.signature([d.stored_path for d in documents])
        labels = tuple(d.label for d in documents)
        key = (int(user_id), signature, labels)
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None:
                self._cache.move_to_end(key)
                return cached
        index = firm.build_index(documents, db_path=self.db_path, progreso=progreso)
        with self._lock:
            for old in [k for k in self._cache if k[0] == int(user_id)]:
                del self._cache[old]          # un índice vigente por usuario
            self._cache[key] = index
            while len(self._cache) > self.MAX_CACHED_INDEXES:
                self._cache.popitem(last=False)
        return index

    def forget_user(self, user_id: int) -> None:
        with self._lock:
            for old in [k for k in self._cache if k[0] == int(user_id)]:
                del self._cache[old]

    # ------------------------------------------------------------ conversaciones
    def create_conversation(self, user_id: int, title: str) -> int:
        with connect(self.db_path) as db:
            return db.execute("INSERT INTO assistant_conversations(user_id, title) VALUES (?, ?)",
                              (user_id, vault.enc_text(title.strip()[:80] or "Nueva consulta"))).lastrowid

    def conversations(self, user_id: int) -> List[dict]:
        with connect(self.db_path) as db:
            rows = db.execute("SELECT id, title, created_at, updated_at FROM assistant_conversations "
                              "WHERE user_id = ? ORDER BY updated_at DESC, id DESC LIMIT 100", (user_id,)).fetchall()
        return [{**dict(r), "title": vault.dec_text(r["title"])} for r in rows]

    def owns(self, user_id: int, conversation_id: int) -> bool:
        with connect(self.db_path) as db:
            return db.execute("SELECT 1 FROM assistant_conversations WHERE id = ? AND user_id = ?",
                              (conversation_id, user_id)).fetchone() is not None

    def delete_conversation(self, user_id: int, conversation_id: int) -> bool:
        with connect(self.db_path) as db:
            return db.execute("DELETE FROM assistant_conversations WHERE id = ? AND user_id = ?",
                              (conversation_id, user_id)).rowcount > 0

    def add_message(self, conversation_id: int, role: str, content: str,
                    sources: Sequence[dict] = (), metadata: Optional[dict] = None) -> int:
        with connect(self.db_path) as db:
            message_id = db.execute(
                "INSERT INTO assistant_messages(conversation_id, role, content, metadata) VALUES (?, ?, ?, ?)",
                (conversation_id, role, vault.enc_text(content),
                 vault.enc_text(json.dumps(metadata or {}, ensure_ascii=False)))).lastrowid
            db.executemany(
                "INSERT INTO assistant_message_sources(message_id, source_type, case_id, document_id, label, "
                "page_start, page_end) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [(message_id, s["source_type"], s["case_id"], s.get("document_id"),
                  vault.enc_text(f"{s.get('case_label', '')}\x1f{s['label']}"), s.get("page_start"), s.get("page_end"))
                 for s in sources])
            db.execute("UPDATE assistant_conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                       (conversation_id,))
        return message_id

    def messages(self, user, conversation_id: int, limit: int = 60) -> List[dict]:
        """Mensajes del propietario, con fuentes re-autorizadas en cada lectura."""
        with connect(self.db_path) as db:
            owner = db.execute("SELECT user_id FROM assistant_conversations WHERE id = ?",
                               (conversation_id,)).fetchone()
            if owner is None or int(owner["user_id"]) != int(user["id"]):
                return []
            rows = db.execute("SELECT id, role, content, created_at FROM assistant_messages "
                              "WHERE conversation_id = ? ORDER BY id DESC LIMIT ?",
                              (conversation_id, limit)).fetchall()[::-1]
            ids = [r["id"] for r in rows]
            src_rows = []
            if ids:
                marks = ",".join("?" for _ in ids)
                src_rows = db.execute(f"SELECT * FROM assistant_message_sources WHERE message_id IN ({marks}) "
                                      "ORDER BY id", ids).fetchall()
            scope = policy.assistant_scope(db, user)
            doc_ok: Dict[int, bool] = {}
            by_message: Dict[int, List[dict]] = {}
            hidden = set()
            for s in src_rows:
                allowed = s["case_id"] in scope
                if allowed and s["source_type"] == "document":
                    if s["document_id"] not in doc_ok:
                        doc = db.execute("SELECT * FROM documents WHERE id = ?", (s["document_id"],)).fetchone()
                        doc_ok[s["document_id"]] = policy.document_allowed(db, user, doc, "documents.view")
                    allowed = doc_ok[s["document_id"]]
                if not allowed:
                    hidden.add(s["message_id"])
                    continue
                case_lbl, _, label = vault.dec_text(s["label"]).partition("\x1f")
                by_message.setdefault(s["message_id"], []).append({
                    "source_type": s["source_type"], "case_id": s["case_id"], "case_label": case_lbl,
                    "document_id": s["document_id"], "label": label,
                    "page_start": s["page_start"], "page_end": s["page_end"],
                })
            can_download = policy.has_permission(db, user, "documents.download")
        out = []
        for r in rows:
            redacted = r["id"] in hidden
            sources = [] if redacted else by_message.get(r["id"], [])
            for s in sources:
                s["downloadable"] = bool(can_download and s["document_id"])
            out.append({"id": r["id"], "role": r["role"], "created_at": r["created_at"], "redacted": redacted,
                        "content": REDACTED if redacted else vault.dec_text(r["content"]), "sources": sources})
        return out

    def history_for_model(self, user, conversation_id: int) -> List[dict]:
        msgs = [m for m in self.messages(user, conversation_id, limit=HISTORY_MESSAGES * 2) if not m["redacted"]]
        return [{"role": m["role"], "content": m["content"]} for m in msgs[-HISTORY_MESSAGES:]]
