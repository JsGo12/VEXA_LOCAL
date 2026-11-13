# Configuración (`.env`)

VEXA lee su configuración en este orden de prioridad:

1. **Variables de entorno del proceso** (por ejemplo, las que fija Electron: `VEXA_HOST`, `VEXA_PORT`, `TAILSCALE_ENABLED=false`).
2. **`Codigo/.env`** (o la ruta de `VEXA_ENV_FILE`). En el instalador: `.env` junto a `VexaBackend.exe` o en `%USERPROFILE%\.vexa_local\.env`.
3. Valores predeterminados seguros.

```powershell
.\.venv\Scripts\python.exe backend\scripts\init_env.py     # crea .env desde .env.example (no sobrescribe)
.\.venv\Scripts\python.exe backend\run.py --check          # valida y muestra dónde escucharía
```

`.env` está en `.gitignore` (raíz y `Codigo/`). Compruébalo con `git check-ignore -v Codigo/.env`. Solo `.env.example` se versiona y no contiene secretos.

## Variables

| Variable | Predeterminado | Descripción |
|---|---|---|
| `VEXA_ENV` | `development` | `production` prohíbe el servidor de desarrollo de Flask. |
| `VEXA_SERVER` | `waitress` | `waitress` o `flask` (solo desarrollo; `run.py --dev` equivale). |
| `VEXA_HOST` | `127.0.0.1` | Solo loopback. Cualquier otra dirección detiene el arranque. |
| `VEXA_PORT` | `5000` | Puerto local. Electron lo reemplaza por uno aleatorio. |
| `VEXA_THREADS` | `8` | Hilos de Waitress (1–64). Cada consulta de chat ocupa un hilo mientras genera. |
| `VEXA_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. |
| `VEXA_SECRET_KEY` | vacío | Firma de sesiones (≥ 32 caracteres). Vacío = `web_secret.key` cifrada con DPAPI (recomendado). |
| `VEXA_ADMIN_USERNAME` / `VEXA_ADMIN_PASSWORD` | vacío | Solo para crear el primer administrador. Contraseña ≥ 12 caracteres. |
| `VEXA_DATA_DIR` | `%USERPROFILE%\.vexa_local` | Carpeta de datos. |
| `VEXA_DB_PATH` | `<DATA_DIR>\vexa_web.db` | Base SQLite. |
| `VEXA_WATCH_DIR` | `<DATA_DIR>\carpeta_vigilada` | Carpeta vigilada (una subcarpeta por caso). |
| `VEXA_SESSION_COOKIE_SECURE` | `false` | `true` si se accede por HTTPS (p. ej. `tailscale serve`). |
| `OLLAMA_HOST` | `http://127.0.0.1:11434` | Debe ser loopback: VEXA no envía documentos a IA externa. |
| `VEXA_CHAT_MODEL` | vacío | Fuerza un modelo de chat (vacío = automático según RAM/GPU). |
| `VEXA_EMBED_MODEL` | `bge-m3` | Modelo de embeddings (si falta, se usa solo BM25). |
| `VEXA_OLLAMA_KEEP_ALIVE` | `5m` | Tiempo que el modelo queda cargado (`0` = descargar al terminar). |
| `VEXA_TESSERACT_CMD` | vacío | Ruta de `tesseract.exe` para OCR. |
| `TAILSCALE_ENABLED` | `false` | Agrega un listener en la IP de Tailscale. Ver [tailscale.md](tailscale.md). |
| `TAILSCALE_BIND_ADDRESS` | vacío | IP 100.x de este equipo (vacío = `tailscale ip -4`). Solo rango Tailscale. |
| `TAILSCALE_PORT` | `VEXA_PORT` | Puerto en la interfaz de Tailscale. |
| `TAILSCALE_HOST` | vacío | Nombre MagicDNS aceptado como `Host` (además de la IP). |
| `VEXA_ENV_FILE` | — | Ruta alternativa del archivo `.env` (solo como variable de entorno). |

## Secretos y claves

| Archivo/variable | Uso | Origen |
|---|---|---|
| `vault.key` | Cifra documentos, historial, fragmentos, vectores, resúmenes. | La crea VEXA; en Windows queda protegida con DPAPI (cuenta de Windows). **Nunca se configura en `.env` ni se reemplaza.** Las claves antiguas sin DPAPI se siguen leyendo y se protegen al primer uso. |
| `web_secret.key` / `VEXA_SECRET_KEY` | Firma las cookies de sesión. | Generada con `secrets.token_hex(32)` y cifrada con el vault, o definida en `.env`. Cambiarla solo cierra sesiones. |
| `credenciales_admin_inicial.txt` | Contraseña inicial del administrador. | Se escribe una vez; bórrala tras entregarla. |

`init_env.py --generate-secret-key` genera una `VEXA_SECRET_KEY` con `secrets.token_urlsafe(48)`; úsalo solo donde no haya DPAPI, porque el `.env` queda en texto plano.

`Settings` oculta los secretos en `repr()` y `safe_summary()`; VEXA no imprime el `.env` ni registra sus valores.
