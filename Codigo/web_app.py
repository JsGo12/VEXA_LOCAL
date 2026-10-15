"""Local-network, role-based VEXA prototype for law-office case workspaces."""
from __future__ import annotations

import hashlib
import io
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
from collections import defaultdict
from threading import Lock, RLock, Thread

from flask import (Flask, Response, abort, flash, g, jsonify, redirect,
                   render_template, request, send_file, session,
                   stream_with_context, url_for)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

import formats
import model_select
import rag_core
import rag_hybrid
import rag_stages
import store
import vault
import watcher


DATA_DIR = Path.home() / ".vexa_local"
UPLOAD_DIR = DATA_DIR / "case_documents"
DB_PATH = DATA_DIR / "vexa_web.db"
ALLOWED_EXTENSIONS = formats.SUPPORTED
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
vault.configure(DATA_DIR)
WATCH_DIR = Path(os.environ.get("VEXA_WATCH_DIR") or (DATA_DIR / "carpeta_vigilada"))
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
store.init(DB_PATH)


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
        wait = store.lock_remaining(DB_PATH, username)
        if wait:
            flash(f"Demasiados intentos fallidos. Espera {wait // 60 + 1} min e inténtalo de nuevo.", "error")
            return render_template("login.html")
        with connect_db() as db:
            user = db.execute("SELECT * FROM users WHERE username = ? AND active = 1", (username,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            store.clear_failed_logins(DB_PATH, username)
            session.clear()
            session["user_id"] = user["id"]
            session["csrf_token"] = secrets.token_urlsafe(32)
            session.permanent = True
            return redirect(url_for("index"))
        store.register_failed_login(DB_PATH, username)
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
        flash("Adjunta al menos un documento admitido al caso.", "error")
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
            flash("Formato no admitido. Usa PDF, DOCX, XLSX, PPTX, TXT o CSV.", "error")
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
                vault.write_encrypted(stored, content)
                stored_paths.append(str(stored))
                db.execute("INSERT INTO documents(case_id, original_name, stored_path, sha256, uploaded_by) VALUES (?, ?, ?, ?, ?)",
                           (case_id, original_name, str(stored), hashlib.sha256(content).hexdigest(), g.user["id"]))
    except Exception:
        for stored in storage_dir.glob("*"):
            stored.unlink(missing_ok=True)
        storage_dir.rmdir()
        raise
    (WATCH_DIR / str(case_id)).mkdir(parents=True, exist_ok=True)
    Thread(target=_precargar_indice, args=(case_id,), daemon=True).start()
    flash("Caso creado y asignado. Sus documentos se están preparando en segundo plano.", "success")
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
    if any(Path(doc["stored_path"]).is_file() for doc in documents):
        Thread(target=_precargar_indice, args=(case_id,), daemon=True).start()
    case_summary = case["summary"]
    if not case_summary and documents:
        first = documents[0]
        try:
            pages = formats.extraer(first["stored_path"], vault.read_bytes(first["stored_path"]))
            if pages:
                full_text = " ".join(pages[0]["text"].split())
                case_summary = full_text[:650] + ("..." if len(full_text) > 650 else "")
        except Exception:
            app.logger.exception("No se pudo generar una vista previa para el caso %s", case_id)
    watch_dir = str(WATCH_DIR / str(case_id)) if g.user["role"] == "admin" else None
    return render_template("case.html", case=case, documents=documents, case_summary=case_summary,
                           watch_dir=watch_dir)


@app.get("/api/ollama/status")
@login_required
def ollama_status():
    perfil = model_select.perfil_actual(ttl=0)
    model_name = perfil.modelo
    try:
        installed = model_select.instalados_ollama()
        ready = any(n == model_name or n.startswith(model_name + ":") for n in installed)
        semantic = any(n.startswith(rag_hybrid.EMBED_MODEL) for n in installed)
        extra = " · búsqueda por significado activa" if semantic else " · solo palabras exactas (falta ollama pull " + rag_hybrid.EMBED_MODEL + ")"
        return jsonify(connected=True, model=model_name, ready=ready,
                       message=(f"Ollama disponible · {model_name}" + extra) if ready else f"Ollama responde, falta descargar {model_name}")
    except Exception:
        return jsonify(connected=False, model=model_name, ready=False,
                       message="Ollama no responde en localhost:11434")


@app.get("/health")
def health():
    """Comprobación mínima para que el lanzador de escritorio espere a Flask."""
    return jsonify(ok=True)


@app.get("/api/case/<int:case_id>/status")
@login_required
def case_status(case_id):
    case_access(case_id)
    with _jobs_lock:
        job = dict(_jobs.get(case_id, {"state": "idle", "progress": 0.0, "message": ""}))
    return jsonify(**job)


@app.get("/api/case/<int:case_id>/history")
@login_required
def case_history(case_id):
    case_access(case_id)
    return jsonify(messages=store.recent_messages(DB_PATH, case_id, g.user["id"], limit=40))


@app.post("/api/case/<int:case_id>/history/clear")
@login_required
def case_history_clear(case_id):
    case_access(case_id)
    store.clear_messages(DB_PATH, case_id, g.user["id"])
    return jsonify(ok=True)


@app.get("/api/case/<int:case_id>/summary")
@login_required
def case_summary_api(case_id):
    case_access(case_id)
    row = store.get_summary(DB_PATH, case_id)
    return jsonify(summary=row[1] if row else None)


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
    return send_file(io.BytesIO(vault.read_bytes(document["stored_path"])), as_attachment=True,
                     download_name=document["original_name"])


_index_cache = OrderedDict()
_answer_cache = OrderedDict()
_rag_cache_lock = RLock()
_build_locks = defaultdict(Lock)
_MAX_CACHED_CASES = 8
_MAX_CACHED_ANSWERS = 128

_jobs = {}        # case_id -> {"state": "running|done|error", "progress": 0-1, "message": str}
_partial = {}     # case_id -> (índice BM25 parcial, documentos listos, total)
_rerun = set()    # casos a los que llegaron archivos nuevos mientras se indexaba
_jobs_lock = RLock()


def _rutas_caso(case_id):
    """(rutas existentes, {ruta: nombre original}) de los documentos del caso."""
    with connect_db() as db:
        rows = db.execute("SELECT original_name, stored_path FROM documents WHERE case_id = ? ORDER BY id", (case_id,)).fetchall()
    rows = [r for r in rows if Path(r["stored_path"]).is_file()]
    return [r["stored_path"] for r in rows], {r["stored_path"]: r["original_name"] for r in rows}


def _firma(paths):
    return tuple((path, Path(path).stat().st_mtime_ns) for path in paths)


def _obtener_indice_caso(case_id, paths, progreso=None, parcial=None):
    """Índice híbrido del caso. El armado ocurre fuera del lock de cachés para no bloquear el chat."""
    signature = _firma(paths)
    cache_key = (case_id, signature)
    with _build_locks[case_id]:
        with _rag_cache_lock:
            index = _index_cache.get(cache_key)
            if index is not None:
                _index_cache.move_to_end(cache_key)
                return index, signature, True
        _, nombres = _rutas_caso(case_id)
        index = rag_hybrid.construir_indice_hibrido(paths, db_path=DB_PATH, progreso=progreso,
                                                    nombres=nombres, parcial=parcial)
        with _rag_cache_lock:
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


def _generar_resumen(case_id, index, signature):
    sig = hashlib.sha1(repr(signature).encode()).hexdigest()
    previo = store.get_summary(DB_PATH, case_id)
    if previo and previo[0] == sig:
        return
    try:
        perfil = model_select.perfil_actual()
        texto = rag_stages.resumir_indice(index, perfil.modelo, opciones=perfil.opciones)
        if texto:
            store.save_summary(DB_PATH, case_id, sig, texto)
    except Exception:
        app.logger.warning("No se pudo generar el resumen automático del caso %s", case_id)


def _precargar_indice(case_id):
    """Indexa en segundo plano (progreso en /api/case/<id>/status). Si llegan archivos nuevos
    durante el proceso, vuelve a indexar hasta 3 veces."""
    with _jobs_lock:
        job = _jobs.get(case_id)
        if job and job["state"] == "running":
            _rerun.add(case_id)
            return
        _jobs[case_id] = {"state": "running", "progress": 0.0, "message": "Iniciando"}
        _rerun.discard(case_id)

    def avance(fraccion, mensaje):
        with _jobs_lock:
            _jobs[case_id].update(progress=round(fraccion, 3), message=mensaje)

    def parcial(indice, hechos, total):
        with _jobs_lock:
            _partial[case_id] = (indice, hechos, total)

    try:
        resultado = None
        for _ in range(3):
            paths, _n = _rutas_caso(case_id)
            if not paths:
                break
            resultado = _obtener_indice_caso(case_id, paths, progreso=avance, parcial=parcial)
            with _jobs_lock:
                if case_id in _rerun:
                    _rerun.discard(case_id)
                    continue
            break
        with _jobs_lock:
            _jobs[case_id] = {"state": "done", "progress": 1.0, "message": "Listo"}
            _partial.pop(case_id, None)
        if resultado:
            index, signature, _hit = resultado
            perfil = model_select.perfil_actual()
            Thread(target=rag_hybrid.precargar_modelo, args=(perfil.modelo,), daemon=True).start()
            Thread(target=_generar_resumen, args=(case_id, index, signature), daemon=True).start()
    except Exception:
        app.logger.exception("No se pudo precargar el índice del caso %s", case_id)
        with _jobs_lock:
            _jobs[case_id] = {"state": "error", "progress": 0.0, "message": "No se pudieron leer los documentos"}
            _partial.pop(case_id, None)


def _ingest_file(case_id, path: Path) -> bool:
    """Agrega un archivo de la carpeta vigilada al caso (cifrado) y lo reindexa."""
    with connect_db() as db:
        case = db.execute("SELECT created_by FROM cases WHERE id = ?", (case_id,)).fetchone()
    name = secure_filename(path.name) or "documento"
    if not case or Path(name).suffix.lower() not in ALLOWED_EXTENSIONS:
        return False
    try:
        if path.stat().st_size > MAX_FILE_SIZE:
            app.logger.warning("Archivo vigilado demasiado grande (%s bytes): %s", MAX_FILE_SIZE, name)
            return False
    except OSError:
        return False
    content = path.read_bytes()
    if not content or len(content) > MAX_FILE_SIZE:
        return False
    storage_dir = UPLOAD_DIR / uuid.uuid4().hex
    storage_dir.mkdir(parents=True, exist_ok=True)
    stored = storage_dir / f"{uuid.uuid4().hex}{Path(name).suffix.lower()}"
    vault.write_encrypted(stored, content)
    with connect_db() as db:
        db.execute("INSERT INTO documents(case_id, original_name, stored_path, sha256, uploaded_by) VALUES (?, ?, ?, ?, ?)",
                   (case_id, name, str(stored), hashlib.sha256(content).hexdigest(), case["created_by"]))
    app.logger.info("Carpeta vigilada: %s agregado al caso %s", name, case_id)
    Thread(target=_precargar_indice, args=(case_id,), daemon=True).start()
    return True


def start_background_services():
    """Cifra archivos antiguos y arranca la carpeta vigilada (una carpeta por caso)."""
    try:
        n = vault.encrypt_existing(UPLOAD_DIR)
        if n:
            app.logger.info("Se cifraron %s archivos existentes.", n)
    except Exception:
        app.logger.exception("No se pudieron cifrar los archivos existentes")
    with connect_db() as db:
        for row in db.execute("SELECT id FROM cases").fetchall():
            (WATCH_DIR / str(row["id"])).mkdir(parents=True, exist_ok=True)
    watcher.CarpetaVigilada(WATCH_DIR, _ingest_file, ALLOWED_EXTENSIONS).start()


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
    paths, _names = _rutas_caso(case_id)
    if not paths:
        return jsonify(ok=False, error="Este caso no tiene documentos disponibles."), 400

    perfil = model_select.perfil_actual()
    notice = ""
    with _jobs_lock:
        job = _jobs.get(case_id)
        part = _partial.get(case_id)
    if job and job["state"] == "running":
        # Se puede preguntar mientras indexa: se usa lo que ya está listo.
        if not part:
            pct = int(job["progress"] * 100)
            return jsonify(ok=False, error=f"VEXA está leyendo el primer documento ({pct}%). Inténtalo en unos segundos."), 409
        index, done, total = part
        signature, index_cache_hit = None, False
        notice = f"Aviso: VEXA aún indexa; esta respuesta usa {done} de {total} documentos.\n\n"
    else:
        try:
            index, signature, index_cache_hit = _obtener_indice_caso(case_id, paths)
        except Exception:
            app.logger.exception("Falló la extracción o indexación del caso %s", case_id)
            return jsonify(ok=False, error="VEXA no pudo leer o preparar los documentos del caso. Revisa que los archivos sean válidos."), 422

    if index.esta_vacio():
        extra = "" if formats.ocr_disponible() else " Si el PDF es escaneado, instala Tesseract para activar el OCR."
        return jsonify(ok=False, error="VEXA no pudo extraer texto de los documentos." + extra), 422

    user_id = g.user["id"]
    history = store.recent_messages(DB_PATH, case_id, user_id, limit=rag_hybrid.HISTORY_TURNS * 2)
    standalone = rag_hybrid.reformular_pregunta(question, history, perfil.modelo)

    answer_key = None
    if signature is not None:
        answer_key = (case_id, signature, " ".join(standalone.casefold().split()), perfil.modelo)
        with _rag_cache_lock:
            cached_answer = _answer_cache.get(answer_key)
            if cached_answer is not None:
                _answer_cache.move_to_end(answer_key)
                answer, sources = cached_answer
                store.add_message(DB_PATH, case_id, user_id, "user", question)
                store.add_message(DB_PATH, case_id, user_id, "assistant", answer, sources)
                return jsonify(ok=True, answer=answer, sources=sources, cached=True)

    staged = rag_stages.es_totalidad(standalone)
    fragments, hits = [], []
    if not staged:
        try:
            top_k = rag_core.determinar_top_k(standalone, len(index.chunks))
            hits = rag_hybrid.buscar_hibrido(standalone, index, top_k=top_k)
            fragments = rag_hybrid.limitar_contexto(rag_hybrid.con_vecinos(hits, index), hits, perfil.max_chars)
        except Exception:
            app.logger.exception("Falló la búsqueda documental del caso %s", case_id)
            return jsonify(ok=False, error="Falló la búsqueda dentro de los documentos. Revisa el terminal del servidor para ver el detalle técnico."), 500
        if not fragments:
            return jsonify(ok=False, error="No encontré información relacionada en este expediente. Prueba con un nombre, fecha, monto o frase que aparezca en el documento."), 422

    @stream_with_context
    def generar_respuesta():
        generation_started = time.perf_counter()
        answer_parts, sources = [], list(dict.fromkeys(f.fuente for f in hits))
        try:
            if notice:
                yield _evento_stream("delta", text=notice)       # se muestra, pero no entra al historial
            if staged:
                for ev in rag_stages.responder_por_etapas(standalone, index, perfil.modelo,
                                                          perfil.opciones, perfil.max_chars):
                    if ev["type"] == "delta":
                        answer_parts.append(ev["text"]); yield _evento_stream("delta", text=ev["text"])
                    elif ev["type"] == "progress":
                        yield _evento_stream("progress", done=ev["done"], total=ev["total"])
                    elif ev["type"] == "sources":
                        sources = ev["sources"]
            else:
                for text_part in rag_hybrid.consultar_stream(
                    standalone, fragments, history, modelo=perfil.modelo, opciones=perfil.opciones,
                ):
                    answer_parts.append(text_part)
                    yield _evento_stream("delta", text=text_part)

            answer = "".join(answer_parts)
            if answer_key is not None:
                with _rag_cache_lock:
                    _answer_cache[answer_key] = (answer, sources)
                    _answer_cache.move_to_end(answer_key)
                    while len(_answer_cache) > _MAX_CACHED_ANSWERS:
                        _answer_cache.popitem(last=False)
            store.add_message(DB_PATH, case_id, user_id, "user", question)
            store.add_message(DB_PATH, case_id, user_id, "assistant", answer, sources)
            app.logger.info(
                "Consulta RAG caso=%s modelo=%s etapas=%s semantico=%s index_cache=%s chunks=%s contexto=%s "
                "reformulada=%s generacion_ms=%.0f total_ms=%.0f",
                case_id, perfil.modelo, staged, index.semantico, index_cache_hit, len(index.chunks), len(fragments),
                standalone != question,
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
    start_background_services()
    # Host de demostración en red local. No exponer este servidor a Internet.
    app.run(host=os.environ.get("VEXA_HOST", "0.0.0.0"),
            port=int(os.environ.get("VEXA_PORT", "5000")), debug=False, threaded=True)
