"""Local-network, role-based VEXA prototype for law-office case workspaces."""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import sys
import time
import uuid
from collections import OrderedDict
from datetime import datetime
from functools import wraps
from pathlib import Path
from threading import RLock, Thread

from flask import (Flask, Response, abort, flash, g, jsonify, redirect,
                   render_template, request, send_file, session,
                   stream_with_context, url_for)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

import rag_core


DATA_DIR = Path.home() / ".vexa_local"
UPLOAD_DIR = DATA_DIR / "case_documents"
DB_PATH = DATA_DIR / "vexa_web.db"
ALLOWED_EXTENSIONS = {".pdf", ".docx"}
MAX_FILE_SIZE = 30 * 1024 * 1024

RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
app = Flask(
    __name__,
    template_folder=str(RESOURCE_DIR / "templates"),
    static_folder=str(RESOURCE_DIR / "static"),
)
app.config.update(
    MAX_CONTENT_LENGTH=100 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=60 * 60 * 8,
)
DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
secret_path = DATA_DIR / "web_secret.key"
if secret_path.exists():
    app.secret_key = secret_path.read_text(encoding="utf-8")
else:
    app.secret_key = secrets.token_hex(32)
    secret_path.write_text(app.secret_key, encoding="utf-8")


def connect_db():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_db():
    with connect_db() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('admin', 'lawyer')),
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS teams (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS team_members (
                team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                PRIMARY KEY(team_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS cases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                reference TEXT NOT NULL DEFAULT '',
                due_at TEXT NOT NULL,
                created_by INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS case_assignments (
                case_id INTEGER PRIMARY KEY REFERENCES cases(id) ON DELETE CASCADE,
                user_id INTEGER REFERENCES users(id),
                team_id INTEGER REFERENCES teams(id),
                CHECK ((user_id IS NOT NULL AND team_id IS NULL) OR
                       (user_id IS NULL AND team_id IS NOT NULL))
            );
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
                original_name TEXT NOT NULL,
                stored_path TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                uploaded_by INTEGER NOT NULL REFERENCES users(id),
                uploaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
        """)
        case_columns = {row["name"] for row in db.execute("PRAGMA table_info(cases)").fetchall()}
        if "summary" not in case_columns:
            db.execute("ALTER TABLE cases ADD COLUMN summary TEXT NOT NULL DEFAULT ''")


initialize_db()


def csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


@app.context_processor
def inject_template_helpers():
    return {"csrf_token": csrf_token}


@app.before_request
def prepare_request():
    csrf_token()
    if request.method == "POST":
        supplied = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
        if not supplied or not secrets.compare_digest(supplied, session.get("csrf_token", "")):
            abort(400, "Token de formulario inválido. Actualiza la página e inténtalo nuevamente.")
    g.user = None
    user_id = session.get("user_id")
    if user_id:
        with connect_db() as db:
            g.user = db.execute(
                "SELECT id, name, username, role FROM users WHERE id = ? AND active = 1",
                (user_id,),
            ).fetchone()
        if g.user is None:
            session.clear()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if g.user["role"] != "admin":
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def case_access(case_id: int):
    """Return a case only if the signed-in user is assigned directly or by team."""
    with connect_db() as db:
        case = db.execute("""
            SELECT c.*, a.user_id AS assigned_user_id, a.team_id,
                   u.name AS assignee_name, t.name AS team_name
            FROM cases c
            JOIN case_assignments a ON a.case_id = c.id
            LEFT JOIN users u ON u.id = a.user_id
            LEFT JOIN teams t ON t.id = a.team_id
            WHERE c.id = ?
        """, (case_id,)).fetchone()
        if case is None:
            abort(404)
        if g.user["role"] == "admin":
            return case
        if case["assigned_user_id"] == g.user["id"]:
            return case
        if case["team_id"] is not None:
            member = db.execute(
                "SELECT 1 FROM team_members WHERE team_id = ? AND user_id = ?",
                (case["team_id"], g.user["id"]),
            ).fetchone()
            if member:
                return case
    abort(403)


def assigned_cases(user_id: int):
    with connect_db() as db:
        return db.execute("""
            SELECT c.*, u.name AS assignee_name, t.name AS team_name,
                   (SELECT COUNT(*) FROM documents d WHERE d.case_id = c.id) AS document_count
            FROM cases c
            JOIN case_assignments a ON a.case_id = c.id
            LEFT JOIN users u ON u.id = a.user_id
            LEFT JOIN teams t ON t.id = a.team_id
            WHERE a.user_id = ? OR a.team_id IN
                (SELECT team_id FROM team_members WHERE user_id = ?)
            ORDER BY c.due_at ASC
        """, (user_id, user_id)).fetchall()


@app.route("/")
def index():
    with connect_db() as db:
        has_users = db.execute("SELECT EXISTS(SELECT 1 FROM users)").fetchone()[0]
    if not has_users:
        return redirect(url_for("setup"))
    if g.user is None:
        return redirect(url_for("login"))
    return redirect(url_for("admin_dashboard" if g.user["role"] == "admin" else "lawyer_dashboard"))


@app.route("/setup", methods=["GET", "POST"])
def setup():
    with connect_db() as db:
        exists = db.execute("SELECT EXISTS(SELECT 1 FROM users)").fetchone()[0]
        if exists:
            return redirect(url_for("login"))
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            if not name or not username or len(password) < 10:
                flash("Completa los campos. La contraseña debe tener al menos 10 caracteres.", "error")
            else:
                db.execute("INSERT INTO users(name, username, password_hash, role) VALUES (?, ?, ?, 'admin')",
                           (name, username, generate_password_hash(password)))
                session.clear()
                flash("Cuenta administradora creada. Inicia sesión para continuar.", "success")
                return redirect(url_for("login"))
    return render_template("setup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("index"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        with connect_db() as db:
            user = db.execute("SELECT * FROM users WHERE username = ? AND active = 1", (username,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["csrf_token"] = secrets.token_urlsafe(32)
            session.permanent = True
            return redirect(url_for("index"))
        flash("Usuario o contraseña incorrectos.", "error")
    return render_template("login.html")


@app.post("/logout")
@login_required
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/admin", methods=["GET", "POST"])
@admin_required
def admin_dashboard():
    with connect_db() as db:
        lawyers = db.execute("SELECT id, name, username FROM users WHERE role = 'lawyer' AND active = 1 ORDER BY name").fetchall()
        teams = db.execute("SELECT id, name FROM teams ORDER BY name").fetchall()
        cases = db.execute("""
            SELECT c.*, u.name AS assignee_name, t.name AS team_name,
                   (SELECT COUNT(*) FROM documents d WHERE d.case_id = c.id) AS document_count
            FROM cases c JOIN case_assignments a ON a.case_id = c.id
            LEFT JOIN users u ON u.id = a.user_id LEFT JOIN teams t ON t.id = a.team_id
            ORDER BY c.due_at ASC
        """).fetchall()
    return render_template("admin.html", lawyers=lawyers, teams=teams, cases=cases)


@app.post("/admin/users")
@admin_required
def create_lawyer():
    name = request.form.get("name", "").strip()
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    if not name or not username or len(password) < 10:
        flash("Completa los campos. La contraseña debe tener al menos 10 caracteres.", "error")
    else:
        try:
            with connect_db() as db:
                db.execute("INSERT INTO users(name, username, password_hash, role) VALUES (?, ?, ?, 'lawyer')",
                           (name, username, generate_password_hash(password)))
            flash("Cuenta de abogado creada.", "success")
        except sqlite3.IntegrityError:
            flash("Ese nombre de usuario ya existe.", "error")
    return redirect(url_for("admin_dashboard"))


@app.post("/admin/teams")
@admin_required
def create_team():
    name = request.form.get("name", "").strip()
    members = list(dict.fromkeys(request.form.getlist("member_ids", type=int)))
    if not name or not members:
        flash("Indica el nombre del equipo y selecciona al menos un abogado.", "error")
    else:
        try:
            with connect_db() as db:
                cursor = db.execute("INSERT INTO teams(name) VALUES (?)", (name,))
                team_id = cursor.lastrowid
                valid_ids = [row[0] for row in db.execute(
                    f"SELECT id FROM users WHERE role = 'lawyer' AND active = 1 AND id IN ({','.join('?' for _ in members)})", members
                ).fetchall()]
                db.executemany("INSERT INTO team_members(team_id, user_id) VALUES (?, ?)",
                               [(team_id, member_id) for member_id in valid_ids])
            flash("Equipo creado.", "success")
        except sqlite3.IntegrityError:
            flash("Ya existe un equipo con ese nombre.", "error")
    return redirect(url_for("admin_dashboard"))


@app.post("/admin/cases")
@admin_required
def create_case():
    title = request.form.get("title", "").strip()
    summary = request.form.get("summary", "").strip()
    reference = request.form.get("reference", "").strip()
    due_at = request.form.get("due_at", "").strip()
    assignment_type = request.form.get("assignment_type")
    raw_assignee = request.form.get("assignee_id", "")
    files = [item for item in request.files.getlist("documents") if item and item.filename]
    if not title or not summary or not due_at or assignment_type not in {"user", "team"} or not raw_assignee:
        flash("Completa el caso, resumen, responsable y fecha límite.", "error")
        return redirect(url_for("admin_dashboard"))
    if not files:
        flash("Adjunta al menos un documento PDF o DOCX al caso.", "error")
        return redirect(url_for("admin_dashboard"))
    try:
        assignee_id = int(raw_assignee)
        due_time = datetime.strptime(due_at, "%Y-%m-%dT%H:%M")
    except ValueError:
        flash("La fecha o el responsable seleccionado no son válidos.", "error")
        return redirect(url_for("admin_dashboard"))
    if due_time <= datetime.now():
        flash("La fecha límite debe ser futura.", "error")
        return redirect(url_for("admin_dashboard"))

    valid_files = []
    stored_paths = []
    for uploaded in files:
        safe_name = secure_filename(uploaded.filename)
        if Path(safe_name).suffix.lower() not in ALLOWED_EXTENSIONS:
            flash("Solo se aceptan archivos PDF o DOCX.", "error")
            return redirect(url_for("admin_dashboard"))
        content = uploaded.read(MAX_FILE_SIZE + 1)
        if len(content) > MAX_FILE_SIZE:
            flash("Cada archivo debe pesar como máximo 30 MB.", "error")
            return redirect(url_for("admin_dashboard"))
        valid_files.append((safe_name or "documento", content))

    storage_dir = UPLOAD_DIR / uuid.uuid4().hex
    storage_dir.mkdir(parents=True, exist_ok=True)
    try:
        with connect_db() as db:
            table, key = ("users", "user_id") if assignment_type == "user" else ("teams", "team_id")
            target = db.execute(f"SELECT id FROM {table} WHERE id = ?", (assignee_id,)).fetchone()
            if not target or (assignment_type == "user" and db.execute(
                "SELECT role FROM users WHERE id = ?", (assignee_id,)
            ).fetchone()[0] != "lawyer"):
                flash("El abogado o equipo seleccionado ya no existe.", "error")
                return redirect(url_for("admin_dashboard"))
            cursor = db.execute("INSERT INTO cases(title, summary, reference, due_at, created_by) VALUES (?, ?, ?, ?, ?)",
                                (title, summary, reference, due_at, g.user["id"]))
            case_id = cursor.lastrowid
            db.execute(f"INSERT INTO case_assignments(case_id, {key}) VALUES (?, ?)", (case_id, assignee_id))
            for original_name, content in valid_files:
                stored = storage_dir / f"{uuid.uuid4().hex}{Path(original_name).suffix.lower()}"
                stored.write_bytes(content)
                stored_paths.append(str(stored))
                db.execute("INSERT INTO documents(case_id, original_name, stored_path, sha256, uploaded_by) VALUES (?, ?, ?, ?, ?)",
                           (case_id, original_name, str(stored), hashlib.sha256(content).hexdigest(), g.user["id"]))
    except Exception:
        for stored in storage_dir.glob("*"):
            stored.unlink(missing_ok=True)
        storage_dir.rmdir()
        raise
    try:
        _obtener_indice_caso(case_id, stored_paths)
        flash("Caso creado y asignado. Sus documentos ya están preparados para consulta.", "success")
    except Exception:
        app.logger.exception("El caso %s se creó, pero no se pudo precargar su índice", case_id)
        flash("Caso creado y asignado. VEXA preparará los documentos al abrir el chat.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/lawyer")
@login_required
def lawyer_dashboard():
    if g.user["role"] == "admin":
        return redirect(url_for("admin_dashboard"))
    return render_template("lawyer.html", cases=assigned_cases(g.user["id"]))


@app.route("/case/<int:case_id>")
@login_required
def case_workspace(case_id):
    case = case_access(case_id)
    with connect_db() as db:
        documents = db.execute("SELECT id, original_name, stored_path, uploaded_at FROM documents WHERE case_id = ? ORDER BY id", (case_id,)).fetchall()
    paths = [doc["stored_path"] for doc in documents if Path(doc["stored_path"]).is_file()]
    if paths:
        # En expedientes antiguos (anteriores a la precarga al subir), empieza
        # a indexar al abrir el caso para no cargar esa espera al primer chat.
        Thread(target=_precargar_indice, args=(case_id, paths), daemon=True).start()
    case_summary = case["summary"]
    if not case_summary and documents:
        first_path = Path(documents[0]["stored_path"])
        try:
            pages = (rag_core.extraer_texto_docx(first_path) if first_path.suffix.lower() == ".docx"
                     else rag_core.extraer_texto_por_pagina(first_path))
            if pages:
                full_text = " ".join(pages[0]["text"].split())
                case_summary = full_text[:650] + ("..." if len(full_text) > 650 else "")
        except Exception:
            app.logger.exception("No se pudo generar una vista previa para el caso %s", case_id)
    return render_template("case.html", case=case, documents=documents, case_summary=case_summary)


@app.get("/api/ollama/status")
@login_required
def ollama_status():
    model_name = WEB_CHAT_MODEL
    try:
        response = rag_core.cliente_ollama(rag_core.OLLAMA_HOST).list()
        models = getattr(response, "models", None)
        if models is None and isinstance(response, dict):
            models = response.get("models", [])
        installed = []
        for model in models or []:
            if isinstance(model, dict):
                installed.append(model.get("model") or model.get("name") or "")
            else:
                installed.append(getattr(model, "model", None) or getattr(model, "name", ""))
        ready = any(name == model_name or name.startswith(model_name + ":") for name in installed)
        return jsonify(connected=True, model=model_name, ready=ready,
                       message=f"Ollama disponible · {model_name} instalado" if ready else f"Ollama responde, falta descargar {model_name}")
    except Exception:
        return jsonify(connected=False, model=model_name, ready=False,
                       message="Ollama no responde en localhost:11434")


@app.get("/health")
def health():
    """Comprobación mínima para que el lanzador de escritorio espere a Flask."""
    return jsonify(ok=True)


@app.get("/documents/<int:document_id>")
@login_required
def download_document(document_id):
    with connect_db() as db:
        document = db.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
    if document is None:
        abort(404)
    case_access(document["case_id"])
    if not Path(document["stored_path"]).is_file():
        abort(404)
    return send_file(document["stored_path"], as_attachment=True, download_name=document["original_name"])


_index_cache = OrderedDict()
_answer_cache = OrderedDict()
_rag_cache_lock = RLock()
_MAX_CACHED_CASES = 8
_MAX_CACHED_ANSWERS = 128
WEB_CHAT_MODEL = "llama3.2:1b"
WEB_CHAT_OPTIONS = {"num_ctx": 2048, "num_batch": 128, "num_predict": 256, "temperature": 0.1}


def _obtener_indice_caso(case_id, paths):
    """Obtiene el índice del expediente de la caché o lo crea una sola vez."""
    signature = tuple((path, Path(path).stat().st_mtime_ns) for path in paths)
    cache_key = (case_id, signature)
    with _rag_cache_lock:
        index = _index_cache.get(cache_key)
        if index is not None:
            _index_cache.move_to_end(cache_key)
            return index, signature, True

        index = rag_core.procesar_documentos(paths)
        # Si cambió el conjunto o contenido de documentos, descarta la versión
        # anterior del mismo caso y sus respuestas asociadas.
        for old_key in [key for key in _index_cache if key[0] == case_id]:
            del _index_cache[old_key]
        for old_key in [key for key in _answer_cache if key[0] == case_id]:
            del _answer_cache[old_key]
        _index_cache[cache_key] = index
        while len(_index_cache) > _MAX_CACHED_CASES:
            evicted_key, _ = _index_cache.popitem(last=False)
            for answer_key in [key for key in _answer_cache if key[0] == evicted_key[0]]:
                del _answer_cache[answer_key]
        return index, signature, False


def _precargar_indice(case_id, paths):
    try:
        _obtener_indice_caso(case_id, paths)
    except Exception:
        app.logger.exception("No se pudo precargar el índice del caso %s", case_id)


def _evento_stream(evento, **datos):
    return json.dumps({"type": evento, **datos}, ensure_ascii=False) + "\n"


def _mensaje_error_ollama(exc):
    if isinstance(exc, rag_core.ollama.ResponseError):
        detail = str(exc).splitlines()[0][:240]
        return f"Ollama recibió la consulta, pero el modelo devolvió un error: {detail}"
    if "ConnectError" in type(exc).__name__ or "Connection refused" in str(exc):
        return "VEXA no pudo conectarse a Ollama en localhost:11434. Abre Ollama en el computador servidor y vuelve a intentarlo."
    return f"Falló la generación con Ollama ({type(exc).__name__}). Revisa el terminal del servidor para ver el detalle técnico."


@app.post("/api/case/<int:case_id>/chat")
@login_required
def case_chat(case_id):
    request_started = time.perf_counter()
    case_access(case_id)
    payload = request.get_json(silent=True) or {}
    question = str(payload.get("question", "")).strip()
    if not question:
        return jsonify(ok=False, error="Escribe una consulta."), 400
    with connect_db() as db:
        documents = db.execute("SELECT original_name, stored_path FROM documents WHERE case_id = ? ORDER BY id", (case_id,)).fetchall()
    paths = [doc["stored_path"] for doc in documents if Path(doc["stored_path"]).is_file()]
    if not paths:
        return jsonify(ok=False, error="Este caso no tiene documentos disponibles."), 400
    try:
        index, signature, index_cache_hit = _obtener_indice_caso(case_id, paths)
    except Exception:
        app.logger.exception("Falló la extracción o indexación del caso %s", case_id)
        return jsonify(ok=False, error="VEXA no pudo leer o preparar los documentos del caso. Revisa que los archivos sean PDF o DOCX válidos."), 422

    if index.esta_vacio():
        return jsonify(ok=False, error="VEXA no pudo extraer texto de los documentos. Si el PDF es escaneado, necesitará OCR antes de consultarlo."), 422

    answer_key = (case_id, signature, " ".join(question.casefold().split()), WEB_CHAT_MODEL)
    with _rag_cache_lock:
        cached_answer = _answer_cache.get(answer_key)
        if cached_answer is not None:
            _answer_cache.move_to_end(answer_key)
            app.logger.info("Consulta respondida desde caché: caso=%s total_ms=%.0f", case_id,
                            (time.perf_counter() - request_started) * 1000)
            answer, sources = cached_answer
            return jsonify(ok=True, answer=answer, sources=sources, cached=True)

    try:
        top_k = rag_core.determinar_top_k(question, len(index.chunks))
        fragments = rag_core.buscar_contexto_relevante(question, index, top_k=top_k)
    except Exception:
        app.logger.exception("Falló la búsqueda documental del caso %s", case_id)
        return jsonify(ok=False, error="Falló la búsqueda dentro de los documentos. Revisa el terminal del servidor para ver el detalle técnico."), 500

    if not fragments:
        return jsonify(ok=False, error="No encontré términos coincidentes en este expediente, así que todavía no consulté Ollama. Prueba con un nombre, fecha, monto o frase que aparezca en el documento."), 422

    sources = list(dict.fromkeys(fragment.fuente for fragment in fragments))

    @stream_with_context
    def generar_respuesta():
        generation_started = time.perf_counter()
        answer_parts = []
        try:
            for text_part in rag_core.consultar_llm_stream(
                question,
                fragments,
                modelo=WEB_CHAT_MODEL,
                opciones=WEB_CHAT_OPTIONS,
            ):
                answer_parts.append(text_part)
                yield _evento_stream("delta", text=text_part)

            answer = "".join(answer_parts)
            with _rag_cache_lock:
                _answer_cache[answer_key] = (answer, sources)
                _answer_cache.move_to_end(answer_key)
                while len(_answer_cache) > _MAX_CACHED_ANSWERS:
                    _answer_cache.popitem(last=False)
            app.logger.info(
                "Consulta RAG caso=%s index_cache=%s chunks=%s contexto=%s "
                "generacion_ms=%.0f total_ms=%.0f",
                case_id, index_cache_hit, len(index.chunks), len(fragments),
                (time.perf_counter() - generation_started) * 1000,
                (time.perf_counter() - request_started) * 1000,
            )
            yield _evento_stream("done", sources=sources, cached=False)
        except Exception as exc:
            app.logger.exception("Error al consultar caso %s", case_id)
            yield _evento_stream("error", error=_mensaje_error_ollama(exc))

    return Response(
        generar_respuesta(),
        mimetype="application/x-ndjson",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


@app.errorhandler(403)
def forbidden(_error):
    return render_template("error.html", code="403", message="No tienes acceso a este caso."), 403


@app.errorhandler(404)
def not_found(_error):
    return render_template("error.html", code="404", message="No encontramos esa página o documento."), 404


@app.errorhandler(400)
def bad_request(error):
    return render_template("error.html", code="400", message=getattr(error, "description", "Solicitud inválida.")), 400


if __name__ == "__main__":
    # Host de demostración en red local. No exponer este servidor a Internet.
    app.run(host=os.environ.get("VEXA_HOST", "0.0.0.0"),
            port=int(os.environ.get("VEXA_PORT", "5000")), debug=False, threaded=True)
