"""Auditoría por páginas, retención automática y prompts centralizados en vexa/rag/prompts.py."""
import re

import pytest

from helpers import _client_as, _web_app, admin_id
from vexa.config import load_settings
from vexa.rag import core as rag_core
from vexa.rag import firm as rag_firm
from vexa.rag import hybrid as rag_hybrid
from vexa.rag import prompts
from vexa.rag import stages as rag_stages
from vexa.services import audit


def _insert_events(web, count, age_days=0):
    with web.connect_db() as db:
        db.executemany(
            "INSERT INTO audit_log(created_at, username, action, result) VALUES "
            "(strftime('%Y-%m-%dT%H:%M:%fZ', 'now', ?), 'prueba', 'auth.login', 'ok')",
            [(f"-{age_days} days",)] * count)


def _count(web):
    with web.connect_db() as db:
        return db.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]


# ------------------------------------------------------------------ páginas
def test_audit_is_paginated(monkeypatch, tmp_path):
    web = _web_app(monkeypatch, tmp_path)
    admin = _client_as(web, admin_id(web))
    _insert_events(web, 120)
    first = admin.get("/admin/audit").get_data(as_text=True)
    assert first.count('<tr class="result-') == 50
    assert 'aria-current="page">1<' in first and "page=2" in first and "page=3" in first
    third = admin.get("/admin/audit?page=3").get_data(as_text=True)
    assert 'aria-current="page">3<' in third and "Mostrando 101–" in third
    beyond = admin.get("/admin/audit?page=99").get_data(as_text=True)            # vuelve a la última
    assert 'aria-current="page">3<' in beyond
    filtered = admin.get("/admin/audit?result=denied").get_data(as_text=True)    # los filtros se mantienen
    assert "Sin eventos para estos filtros." in filtered and 'class="pagination"' not in filtered


# --------------------------------------------------------------- retención
def test_old_audit_events_are_purged(monkeypatch, tmp_path):
    web = _web_app(monkeypatch, tmp_path)
    _insert_events(web, 3, age_days=20)
    _insert_events(web, 2, age_days=3)
    before = _count(web)
    assert audit.purge_older_than(web.settings.db_path, 14) == 3
    assert _count(web) == before - 3
    assert audit.purge_older_than(web.settings.db_path, 0) == 0                  # 0 = conservar todo


def test_audit_page_applies_retention_and_explains_it(monkeypatch, tmp_path):
    web = _web_app(monkeypatch, tmp_path)
    _insert_events(web, 4, age_days=30)
    text = _client_as(web, admin_id(web)).get("/admin/audit").get_data(as_text=True)
    with web.connect_db() as db:
        assert db.execute("SELECT COUNT(*) FROM audit_log WHERE created_at < strftime('%Y-%m-%dT%H:%M:%fZ', "
                          "'now', '-14 days')").fetchone()[0] == 0
    assert "se conservan 14 días" in text


def test_retention_setting_is_validated():
    assert load_settings({}, use_env_file=False).audit_retention_days == 14
    assert load_settings({"VEXA_AUDIT_RETENTION_DAYS": "7"}, use_env_file=False).audit_retention_days == 7
    assert load_settings({"VEXA_AUDIT_RETENTION_DAYS": "0"}, use_env_file=False).audit_retention_days == 0
    with pytest.raises(Exception):
        load_settings({"VEXA_AUDIT_RETENTION_DAYS": "-3"}, use_env_file=False)


# ----------------------------------------------------------------- prompts
def test_prompts_live_in_one_file_and_modules_use_them():
    assert rag_core.PROMPT_SISTEMA is prompts.PROMPT_SISTEMA
    assert rag_hybrid.PROMPT_SISTEMA is prompts.PROMPT_CHAT_CASO
    assert rag_firm.PROMPT_FIRMA is prompts.PROMPT_ASISTENTE_FIRMA
    assert rag_hybrid.PROMPT_REFORMULAR is prompts.PROMPT_REFORMULAR
    assert rag_stages.PROMPT_EXTRAER is prompts.PROMPT_EXTRAER
    # Las defensas contra inyección y la palabra clave que usa el código siguen presentes.
    assert "no instrucciones" in prompts.PROMPT_SISTEMA
    assert prompts.PROMPT_ASISTENTE_FIRMA.startswith(prompts.PROMPT_CHAT_CASO)
    assert "responde exactamente: NADA" in prompts.PROMPT_EXTRAER
    # Ningún módulo del RAG vuelve a definir textos de prompt a mano.
    from pathlib import Path
    rag_dir = Path(rag_core.__file__).parent
    for name in ("core.py", "hybrid.py", "firm.py", "stages.py"):
        source = (rag_dir / name).read_text(encoding="utf-8")
        assert not re.search(r'^PROMPT_\w+ = ["(]', source, re.M), name


def test_prompt_template_keeps_the_exact_format_and_braces_in_questions():
    chunks = [rag_core.Chunk(doc_name="a.pdf", page_number=1, chunk_index=0, text="Texto {raro} uno")]
    built = rag_core.construir_prompt("¿Qué dice {x}?", chunks)
    assert built == ("CONTEXTO:\n[Fragmento 1 — Fuente: " + chunks[0].fuente + "]\nTexto {raro} uno\n\n"
                     "PREGUNTA: ¿Qué dice {x}?\nResponde solo con base en el contexto.")
