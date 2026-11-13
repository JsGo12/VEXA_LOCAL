# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

VEXA Local: an academic prototype of a Windows desktop/private-server app for legal case files ("expedientes") with local RAG over Ollama. Roles: `admin`, `chief_lawyer`, `lawyer`. Lawyers see only their scoped cases; the chief lawyer also has a cross-case ("transversal") assistant. Everything runs locally; use only synthetic documents. Code identifiers, comments, UI text and docs are in Spanish — keep that convention.

## Repository layout caveats

- `Codigo/` (this directory) is the active app. The repo root only has `README.md`, the `run.py` forwarder and `historico/` (the previous version's code and docs under `historico/version_anterior/`, reference only) — never edit `historico/` for app changes.
- Git tracks some paths as `Codigo/...` and new ones may show as `codigo/...` (Windows is case-insensitive, git is not); check casing before staging.
- `legacy/` holds the old Tkinter/pywebview UIs; they import `vexa.rag.core` via a path shim and bypass permissions — not part of the product.

## Commands

Run from `Codigo/` (venv at `Codigo/.venv`, Python 3.14):

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt        # backend + pytest
.\.venv\Scripts\python.exe backend\scripts\init_env.py                # create .env from .env.example (never overwrites)
.\.venv\Scripts\python.exe backend\run.py --check                     # validate config, show listen addresses
.\.venv\Scripts\python.exe backend\run.py                             # Waitress on 127.0.0.1:5000 (+ Tailscale IP if enabled)
.\.venv\Scripts\python.exe backend\run.py --dev                       # Flask dev server, loopback only
.\.venv\Scripts\python.exe -m pytest -q backend\tests                 # all tests
.\.venv\Scripts\python.exe -m pytest -q backend\tests\test_permissions.py -k chief   # subset
Set-Location desktop\electron; .\setup-dev.ps1                        # Electron first run; later: corepack pnpm start
powershell -ExecutionPolicy Bypass -File .\desktop\build.ps1          # PyInstaller + NSIS installer
```

No linter is configured. Tests never read the real `.env` (conftest sets `VEXA_ENV_FILE` to a missing file) and build apps in temp dirs via `tests/helpers.py` (`_web_app`, `_seed_case`, `_client_as`, `add_user`, `add_case`, `add_document`, `grant`). Streamed (NDJSON) responses must be consumed (`response.get_data()`) in tests or the generator never runs.

## Architecture

**Entry points.** `backend/run.py` → `vexa.server.serve()` (instance lock `vexa_server.lock`, publishes `server.json` with the local port, Waitress `listen=` explicit addresses) → `vexa.create_app(settings, listeners)`. `create_app` applies engine settings (vault dir, Ollama host, models, OCR), runs `database.migrations.migrate()` (backs up first), bootstraps the initial admin, registers blueprints, and wraps WSGI in `security.network.RemoteAddressFilter`. Per-app state lives in `app.extensions["vexa"]` (`Runtime`: `settings`, `indexer: CaseIndexer`, `assistant: FirmAssistant`); access it with `vexa.runtime()`.

**Config.** `vexa/config` merges process env over `Codigo/.env` over defaults into a frozen `Settings`. Validation is strict and intentional: `VEXA_HOST` must be loopback, `OLLAMA_HOST` must be loopback, `TAILSCALE_BIND_ADDRESS` must be in 100.64.0.0/10. Don't relax these. Data defaults to `%USERPROFILE%\.vexa_local` (outside the OneDrive-synced repo on purpose); the DB stores absolute document paths.

**Layers** (no cycles; `test_every_backend_module_imports_without_cycles` imports everything): `routes/*` (thin blueprints: `auth`, `system`, `admin`, `access`, `audit_log`, `cases`, `assistant`) → `permissions` (decorators/guards) + `services/*` → `rag/*`, `database/*`, `security/*`. Endpoint names are blueprint-qualified (`cases.case_workspace`, `admin.dashboard`…).

**Authorization** (`permissions/policy.py`, documented in `docs/permisos.md`): functional permissions = role defaults (`catalog.ROLE_PERMISSIONS`) ± `user_permissions` overrides (deny wins). Data scope = assignment (direct/team) ∪ explicit `access_grants` (`case`/`team`/`firm`) — roles never grant data; the admin's global access is a migrated `firm` grant. Document rule order: no permission → deny; out of scope → deny; `document_acl` deny → deny; `documents.restricted` → only with acl allow (overrides firm scope); else allow. Anti-escalation checks (`check_*` in policy) forbid self-modification, non-admins managing non-lawyers, and granting what you don't hold. Every guard failure is audited (`services/audit.py`) — never log passwords, questions or document content.

**RAG.** `rag/core` (Chunk, BM25, prompts, `cliente_ollama(host=None)`), `rag/hybrid` (clause chunking, embeddings via Ollama with BM25 fallback, RRF, follow-up rewriting, `consultar_stream(..., sistema=)`), `rag/stages` (map-reduce for "totality" questions, summaries), `rag/firm` (multi-case retrieval with case/doc/page sources; receives only pre-authorized documents). Ollama host/model defaults are resolved at call time — use `None` defaults, never bind `rag_core.OLLAMA_HOST` as a default argument.

**Cache safety.** `services/indexing.CaseIndexer` keys indexes by `(case_id, signature)` where the signature covers exactly the authorized document set (path, sha, size, mtime), and answers by `(case_id, signature, user_id, question, model)`. Background indexing and auto-summaries use only unrestricted documents; the partial index is used during indexing only if it is a subset of the user's authorized paths. `FirmAssistant` caches per `(user_id, signature)`. Stored assistant answers are re-authorized on read and redacted if a cited source is no longer visible.

**Database.** `database.connect()` returns a connection whose `with` block commits/rolls back AND closes. Schema changes go through `database/migrations.py` (`PRAGMA user_version`, one transaction per migration, use `_run_script` not `executescript`). `store.py` holds chunk/embedding cache, case chat history, summaries, login lockout. Encrypted columns use `vault.enc_text` (`enc:` prefix); files use `vault.write_encrypted`/`read_bytes` (`VEXAENC1` magic). Never replace `vault.key`; the Flask session secret (`VEXA_SECRET_KEY` or encrypted `web_secret.key`) is separate.

**Frontend.** `frontend/templates` + `frontend/static/{css,js,img}`. CSP forbids inline scripts/styles: pass data via `data-*` attributes and `<meta name="csrf-token">`; JS uses `textContent` only. All POSTs need the CSRF token (form field or `X-CSRF-Token`). Chat/assistant responses are NDJSON (`status|delta|progress|done|error`), parsed by `static/js/ndjson.js`.

**Electron.** `desktop/electron/main.js` attaches to an existing server via `server.json` + `/health` (`app: "vexa"`), else spawns `backend/run.py` on a random loopback port with `TAILSCALE_ENABLED=false`; exit codes 2 (config) / 3 (already running) are handled. Packaged builds run `resources/backend/VexaBackend.exe`; PyInstaller paths are in `desktop/build.ps1`.

**Progress & accounts.** `cases.status`/`cases.progress` + `case_updates` (encrypted notes; `services/cases.update_progress`, `follow_up`), route `/case/<id>/progress` (`cases.update_progress`), `/admin/seguimiento` (`cases.manage`, metadata only; traffic light via `deadline_state` vencido/pronto/al_dia; admin-only `cases.set_deadline` → `POST /admin/cases/<id>/due`, audited). Accounts created by others get `must_change_password=1`; `security/http.py` gates every route except `auth.change_password`/logout/static/health until changed. `users.session_epoch` is stored in the session at login and bumped on password change/reset, deactivation and role change, which invalidates other sessions. Test helper `admin_id()` clears the bootstrap admin's pending change.

**Deployment.** One server PC runs `backend/run.py` (scheduled task via `scripts/servidor/registrar-inicio.ps1`); lawyer PCs use a browser or Electron in remote-client mode (`VEXA_REMOTE_URL` or `<data_dir>/cliente.json`, Tailscale/loopback hosts only, written by `desktop/electron/configurar-cliente.ps1`). The repo-root `run.py` just forwards to `Codigo/backend/run.py`. PowerShell scripts are saved as UTF-8 with BOM (Windows PowerShell 5.1). See `docs/despliegue.md`. Docker alternative (`Dockerfile`, `docker-compose.yml`, `docs/docker.md`): vexa and ollama use `network_mode: service:tailscale` so loopback/Tailscale-only binding still holds — no `ports:`, Ollama forced to 127.0.0.1, Tailscale IP detected from the `tailscale*` interface; no DPAPI on Linux, Windows data dirs aren't portable.

## Docs

`docs/` covers architecture, execution, `.env`, Tailscale (no Funnel, ACLs, firewall), permissions, migrations, backups and security. Update the relevant doc when changing behavior.
