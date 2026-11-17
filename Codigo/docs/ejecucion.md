# Instalación y ejecución en Windows

## 1. Instalar programas

| Programa | Uso | Comprobación |
|---|---|---|
| [Python 3](https://www.python.org/downloads/windows/) (marca *Add to PATH*) | Backend | `python --version` |
| [Node.js LTS](https://nodejs.org/en/download/) (≥ 22.12, incluye Corepack) | Electron | `node -v` |
| [Ollama](https://ollama.com/download/windows) | IA local | `ollama list` |
| [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) (opcional) | PDF escaneados | `tesseract --version` |
| [Tailscale](https://tailscale.com/download/windows) (opcional) | Acceso privado remoto | `tailscale status` |

Cierra y vuelve a abrir PowerShell/VS Code después de instalar.

## 2. Modelos de Ollama

```powershell
ollama pull llama3.2:1b      # mínimo para el chat
ollama pull bge-m3           # opcional: búsqueda por significado
```

VEXA elige el mejor modelo instalado según RAM/GPU (`llama3.1:8b` › `llama3.2` › `llama3.2:1b`) o el de `VEXA_CHAT_MODEL`.

## 3. Dependencias de Python

Desde `Codigo/`:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

`requirements.txt` instala `backend/requirements.txt` (ejecución: Flask, Waitress, python-dotenv, extractores, cryptography…) y `pytest`.

## 4. Configuración

```powershell
.\.venv\Scripts\python.exe backend\scripts\init_env.py
.\.venv\Scripts\python.exe backend\run.py --check
```

Ver [configuracion.md](configuracion.md).

## 5. Ejecutar

### Aplicación de escritorio (Electron)

```powershell
Set-Location .\desktop\electron
.\setup-dev.ps1              # primera vez (instala dependencias de Electron con Corepack/pnpm)
corepack pnpm start          # siguientes veces
```

Electron:
- Si ya hay un servidor VEXA activo con la misma carpeta de datos (`server.json`), se conecta a él.
- Si no, inicia `backend\run.py` con el Python de `Codigo\.venv` (o `VEXA_PYTHON`, o `python` del PATH) en un puerto aleatorio de `127.0.0.1` y con Tailscale desactivado.
- Al cerrar la ventana detiene solo el servidor que inició él.

### Servidor independiente con Waitress

```powershell
.\.venv\Scripts\python.exe backend\run.py
```

Abre `http://127.0.0.1:5000`. Usa este modo para el acceso por Tailscale ([tailscale.md](tailscale.md)); Electron en el mismo equipo se conectará a este servidor en vez de iniciar otro.

Códigos de salida: `2` configuración inválida, `3` ya hay un servidor con esa carpeta de datos, `4` no se pudo abrir el puerto.

### Modo desarrollo de Flask

```powershell
.\.venv\Scripts\python.exe backend\run.py --dev
```

Solo loopback, sin recarga automática, prohibido con `VEXA_ENV=production`.

## 6. Pruebas

```powershell
.\.venv\Scripts\python.exe -m pytest -q backend\tests
```

Las pruebas crean su propia carpeta temporal y nunca leen el `.env` real ni `%USERPROFILE%\.vexa_local`.

## 7. Instalador de Windows

```powershell
powershell -ExecutionPolicy Bypass -File .\desktop\build.ps1
```

Crea `desktop\backend\.venv`, empaqueta `backend\run.py` con PyInstaller (`VexaBackend.exe`, incluye `frontend\templates` y `frontend\static`) y genera el instalador NSIS en `desktop\electron\release`. Ollama y los modelos se instalan aparte.

## 8. Reiniciar los datos

Cierra VEXA y elimina `%USERPROFILE%\.vexa_local` (o tu `VEXA_DATA_DIR`). Se borran base, documentos, índices y claves de forma irreversible; haz antes un respaldo ([respaldos.md](respaldos.md)).

## Solución de problemas

| Síntoma | Acción |
|---|---|
| `Configuración inválida: …` | Corrige la variable indicada en `.env`; `run.py --check` muestra el detalle. |
| «Ya hay un servidor VEXA activo» | Cierra el otro proceso (o usa Electron, que se conecta a él). |
| «Ollama no responde» | Abre Ollama y comprueba `ollama list`. |
| Electron: «El proceso del backend terminó» | Ejecuta `backend\run.py` en una terminal para ver el error. |
| PDF escaneado sin texto | Instala Tesseract o define `VEXA_TESSERACT_CMD`. |
