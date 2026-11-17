-- Esquema de referencia de VEXA Local (versión 9 del esquema)
-- Fuente: Codigo/backend/vexa/database/migrations.py (tablas de gestión, permisos y asistente)
--         y Codigo/backend/vexa/database/store.py (procesamiento, chat y login).
-- Código de referencia: carpeta Codigo/ del repositorio VEXA_LOCAL (versión final de la Fase 2).
--
-- El backend crea y migra estas tablas automáticamente (PRAGMA user_version = 9); este archivo
-- las reúne en su forma final para consulta y para crear una base vacía.
-- Los tipos TEXT y BLOB no implican cifrado de SQLite: las columnas marcadas como cifradas se
-- protegen en la aplicación con la capa vault.py (Fernet).
-- Las tablas doc_chunks, doc_embeddings, chat_messages, case_summaries y login_attempts no
-- declaran claves foráneas, igual que el código; sus relaciones se resuelven en la aplicación.

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- ============================ Gestión ============================

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'chief_lawyer', 'lawyer')),
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    must_change_password INTEGER NOT NULL DEFAULT 0,
    session_epoch INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS teams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS team_members (
    team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    PRIMARY KEY (team_id, user_id)
);

CREATE TABLE IF NOT EXISTS cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    reference TEXT NOT NULL DEFAULT '',
    due_at TEXT NOT NULL,
    created_by INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status TEXT NOT NULL DEFAULT 'en_curso'
        CHECK (status IN ('pendiente', 'en_curso', 'en_revision', 'cerrado')),
    progress INTEGER NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
    close_reason TEXT NOT NULL DEFAULT ''     -- motivo de cierre (migración 8)
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
    uploaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    restricted INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS case_updates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id),
    status TEXT NOT NULL,
    progress INTEGER NOT NULL,
    note TEXT NOT NULL DEFAULT '',            -- cifrada cuando no está vacía
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    kind TEXT NOT NULL DEFAULT 'avance' CHECK (kind IN ('avance', 'nota')),   -- migración 6
    close_reason TEXT NOT NULL DEFAULT ''     -- migración 8
);
CREATE INDEX IF NOT EXISTS idx_case_updates_case ON case_updates(case_id, id);

-- ============ Supervisión, notificaciones y mensajes (migraciones 6, 7 y 9) ============

-- Abogados a cargo de cada abogado jefe (migración 6).
CREATE TABLE IF NOT EXISTS chief_lawyers (
    chief_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    lawyer_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (chief_id, lawyer_id)
);
CREATE INDEX IF NOT EXISTS idx_chief_lawyers_lawyer ON chief_lawyers(lawyer_id);

-- Notificaciones dentro de la aplicación: solo metadatos del caso (migración 7).
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    message TEXT NOT NULL DEFAULT '',
    case_id INTEGER REFERENCES cases(id) ON DELETE CASCADE,
    dedupe_key TEXT,                          -- evita repetir recordatorios por la misma fecha
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    read_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id, read_at, id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_notifications_dedupe ON notifications(user_id, dedupe_key)
    WHERE dedupe_key IS NOT NULL;

-- Conversación del equipo en cada caso (migración 9).
CREATE TABLE IF NOT EXISTS case_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id),     -- NULL en los avisos automáticos
    kind TEXT NOT NULL DEFAULT 'mensaje' CHECK (kind IN ('mensaje', 'sistema')),
    body TEXT NOT NULL,                       -- cifrado
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_case_messages_case ON case_messages(case_id, id);

CREATE TABLE IF NOT EXISTS case_message_reads (
    case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    last_read_id INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (case_id, user_id)
);

-- ===================== Permisos, alcance y auditoría =====================

CREATE TABLE IF NOT EXISTS user_permissions (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    permission TEXT NOT NULL,
    effect TEXT NOT NULL CHECK (effect IN ('allow', 'deny')),
    granted_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, permission)
);

CREATE TABLE IF NOT EXISTS access_grants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    scope_type TEXT NOT NULL CHECK (scope_type IN ('firm', 'team', 'case')),
    scope_id INTEGER,
    granted_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK ((scope_type = 'firm' AND scope_id IS NULL) OR
           (scope_type <> 'firm' AND scope_id IS NOT NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_access_grants_unique
    ON access_grants(user_id, scope_type, IFNULL(scope_id, 0));

CREATE TABLE IF NOT EXISTS document_acl (
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    effect TEXT NOT NULL CHECK (effect IN ('allow', 'deny')),
    granted_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (document_id, user_id)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    user_id INTEGER,                          -- sin clave foránea: el registro sobrevive a la cuenta
    username TEXT,
    action TEXT NOT NULL,
    resource_type TEXT,
    resource_id TEXT,
    result TEXT NOT NULL CHECK (result IN ('ok', 'denied', 'error')),
    reason TEXT,
    ip TEXT,
    details TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at);
CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id, created_at);

-- ========================= Asistente transversal =========================

CREATE TABLE IF NOT EXISTS assistant_conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,                      -- cifrado
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_assistant_conv_user ON assistant_conversations(user_id, updated_at);

CREATE TABLE IF NOT EXISTS assistant_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES assistant_conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,                    -- cifrado
    metadata TEXT NOT NULL DEFAULT '',        -- cifrado
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_assistant_msg_conv ON assistant_messages(conversation_id, id);

CREATE TABLE IF NOT EXISTS assistant_message_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL REFERENCES assistant_messages(id) ON DELETE CASCADE,
    source_type TEXT NOT NULL CHECK (source_type IN ('document', 'case')),
    case_id INTEGER NOT NULL,                 -- relación lógica con cases
    document_id INTEGER,                      -- relación lógica con documents
    label TEXT NOT NULL,                      -- cifrado
    page_start INTEGER,
    page_end INTEGER
);
CREATE INDEX IF NOT EXISTS idx_assistant_src_msg ON assistant_message_sources(message_id);

-- ================= Procesamiento, chat por caso y seguridad =================

CREATE TABLE IF NOT EXISTS doc_chunks (
    doc_sha TEXT NOT NULL,                    -- documents.sha256 (relación lógica)
    chunker TEXT NOT NULL,
    idx INTEGER NOT NULL,
    page INTEGER NOT NULL,
    page_end INTEGER,
    text TEXT NOT NULL,                       -- cifrado
    PRIMARY KEY (doc_sha, chunker, idx)
);

CREATE TABLE IF NOT EXISTS doc_embeddings (
    doc_sha TEXT NOT NULL,
    chunker TEXT NOT NULL,
    model TEXT NOT NULL,
    idx INTEGER NOT NULL,
    vec BLOB NOT NULL,                        -- cifrado
    PRIMARY KEY (doc_sha, chunker, model, idx)
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER NOT NULL,                 -- relación lógica con cases
    user_id INTEGER NOT NULL,                 -- relación lógica con users
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,                    -- cifrado
    sources TEXT NOT NULL DEFAULT '',         -- cifrado
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_chat_case_user ON chat_messages(case_id, user_id, id);

CREATE TABLE IF NOT EXISTS case_summaries (
    case_id INTEGER PRIMARY KEY,              -- relación lógica con cases
    signature TEXT NOT NULL,
    summary TEXT NOT NULL,                    -- cifrado
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS login_attempts (
    username TEXT PRIMARY KEY COLLATE NOCASE,
    failed INTEGER NOT NULL DEFAULT 0,
    locked_until REAL NOT NULL DEFAULT 0
);

PRAGMA user_version = 9;
