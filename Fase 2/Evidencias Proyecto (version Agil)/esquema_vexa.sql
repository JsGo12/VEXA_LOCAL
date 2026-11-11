-- Esquema de referencia de VEXA Local

-- Espejo de las sentencias CREATE TABLE en VexaApp/web_app.py y store.py, rama main.

-- El backend crea estas tablas automáticamente. Ejecutar sobre una base vacía.

-- En versiones antiguas web_app.py agrega cases.summary mediante migración.

-- No se agregan FKs a doc_chunks/doc_embeddings/chat_messages/case_summaries porque

-- el código actual tampoco las define. Los tipos TEXT/BLOB no implican cifrado SQL:

-- el cifrado lo aplica la capa vault.py en la aplicación.
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 name TEXT NOT NULL,
 username TEXT NOT NULL UNIQUE COLLATE NOCASE,
 password_hash TEXT NOT NULL,
 role TEXT NOT NULL CHECK (role IN ('admin','lawyer')),
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
 PRIMARY KEY (team_id,user_id)
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
CREATE TABLE IF NOT EXISTS doc_chunks (
 doc_sha TEXT NOT NULL, chunker TEXT NOT NULL, idx INTEGER NOT NULL,
 page INTEGER NOT NULL, page_end INTEGER, text TEXT NOT NULL,
 PRIMARY KEY (doc_sha,chunker,idx)
);
CREATE TABLE IF NOT EXISTS doc_embeddings (
 doc_sha TEXT NOT NULL, chunker TEXT NOT NULL, model TEXT NOT NULL,
 idx INTEGER NOT NULL, vec BLOB NOT NULL,
 PRIMARY KEY (doc_sha,chunker,model,idx)
);
CREATE TABLE IF NOT EXISTS chat_messages (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 case_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
 role TEXT NOT NULL CHECK (role IN ('user','assistant')),
 content TEXT NOT NULL, sources TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_chat_case_user
 ON chat_messages(case_id,user_id,id);
CREATE TABLE IF NOT EXISTS case_summaries (
 case_id INTEGER PRIMARY KEY,
 signature TEXT NOT NULL, summary TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS login_attempts (
 username TEXT PRIMARY KEY COLLATE NOCASE,
 failed INTEGER NOT NULL DEFAULT 0,
 locked_until REAL NOT NULL DEFAULT 0
);
