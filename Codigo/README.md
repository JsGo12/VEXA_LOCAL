# VEXA Local

VEXA es una aplicación jurídica **local y privada** para organizar expedientes y consultar sus documentos con IA que se ejecuta en el propio equipo (Ollama). Un administrador o abogado/a jefe crea cuentas, equipos y casos; cada abogado ve solo los expedientes de su alcance; el abogado jefe dispone además de un **asistente transversal** que busca en todos los expedientes que tiene autorizados.

> Prototipo académico. Usa documentos ficticios; no cargues expedientes reales ni datos personales.

## Qué incluye

- **Backend Flask modular** (`backend/vexa`) servido por **Waitress**, solo en `127.0.0.1` por defecto.
- **Frontend** separado (`frontend/`): plantillas Jinja, CSS y JS sin scripts en línea (CSP estricta).
- **Electron** (`desktop/`) abre la interfaz en una ventana de escritorio.
- **SQLite** con migraciones versionadas y respaldo automático previo.
- **Cifrado en reposo** (Fernet + DPAPI) de documentos, historial, fragmentos, vectores y resúmenes.
- **Roles y permisos granulares** con denegación por defecto: administrador, abogado/a jefe y abogado/a.
- **Avance de casos** (estado, porcentaje, notas cifradas) y **panel de seguimiento** para el administrador.
- **Cuentas**: contraseña temporal obligatoria de cambiar, cambio propio y restablecimiento por el administrador.
- **Chat por expediente** y **asistente IA transversal** con fuentes verificables (expediente, documento, página).
- **Auditoría** de accesos, cambios de permisos, descargas y accesos denegados.
- **Tailscale opcional** para acceso privado desde dispositivos autorizados (nunca Funnel ni puertos públicos).

## Inicio rápido en Windows

Requisitos: Windows 10/11 de 64 bits, [Python 3](https://www.python.org/downloads/windows/), [Node.js LTS](https://nodejs.org/en/download/) y [Ollama](https://ollama.com/download/windows). La configuración inicial necesita Internet para descargar dependencias y modelos; las consultas no.

```powershell
# 1. Modelos locales (bge-m3 es opcional: habilita la búsqueda por significado)
ollama pull llama3.2:1b
ollama pull bge-m3

# 2. Dependencias de Python (desde la carpeta Codigo)
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 3. Configuración local (.env a partir de .env.example; no se sube a Git)
.\.venv\Scripts\python.exe backend\scripts\init_env.py
.\.venv\Scripts\python.exe backend\run.py --check

# 4a. Aplicación de escritorio (Electron inicia el backend por su cuenta)
Set-Location .\desktop\electron
.\setup-dev.ps1            # primera vez; luego: corepack pnpm start

# 4b. O bien, solo el servidor (Waitress) para usarlo desde el navegador o por Tailscale
.\.venv\Scripts\python.exe backend\run.py   # http://127.0.0.1:5000
```

En el primer inicio VEXA crea el usuario `admin` y escribe su contraseña aleatoria en `%USERPROFILE%\.vexa_local\credenciales_admin_inicial.txt`. Entrégala al administrador y borra el archivo.

## Pruebas

```powershell
.\.venv\Scripts\python.exe -m pytest -q backend\tests                       # todas
.\.venv\Scripts\python.exe -m pytest -q backend\tests\test_permissions.py   # un archivo
.\.venv\Scripts\python.exe -m pytest -q backend\tests -k asistente          # por nombre
```

La prueba de OCR se omite si Tesseract no está instalado.

## Estructura

```text
Codigo/
├── backend/            Backend Python
│   ├── run.py          Punto de entrada (Waitress | --dev | --check)
│   ├── vexa/           Paquete de la aplicación (config, database, security, permissions,
│   │                   services, rag, routes)
│   ├── scripts/        init_env.py, backup_vexa.py, eval_rag.py
│   ├── evals/          Conjunto de evaluación RAG ficticio
│   └── tests/          Pruebas (pytest)
├── frontend/           templates/ y static/ (css, js, img)
├── desktop/            Electron (electron/) y empaquetado PyInstaller (backend/, build.ps1)
├── scripts/servidor/   Tarea de inicio, firewall de Tailscale y respaldo semanal (PowerShell)
├── docs/               Documentación técnica
├── legacy/             Interfaces antiguas (Tkinter, pywebview), solo referencia
├── .env.example        Plantilla de configuración
├── Dockerfile, docker-compose.yml   Servidor en contenedores (docs/docker.md)
└── requirements.txt    Instala backend + herramientas de prueba
```

Los **datos** no viven en el repositorio: por defecto están en `%USERPROFILE%\.vexa_local` (base `vexa_web.db`, `case_documents/`, `vault.key`, `carpeta_vigilada/`, `backups/`). Así no se sincronizan con OneDrive ni se suben a GitHub por accidente.

## Documentación

| Tema | Archivo |
|---|---|
| Arquitectura, backend y frontend | [docs/arquitectura.md](docs/arquitectura.md) |
| **Despliegue en la firma (servidor + PCs de abogados)** | [docs/despliegue.md](docs/despliegue.md) |
| Instalación y ejecución (Electron, Waitress, desarrollo) | [docs/ejecucion.md](docs/ejecucion.md) |
| Servidor en Docker (Tailscale + Ollama + VEXA) | [docs/docker.md](docs/docker.md) |
| Variables de `.env` | [docs/configuracion.md](docs/configuracion.md) |
| Acceso privado con Tailscale | [docs/tailscale.md](docs/tailscale.md) |
| Roles, permisos y precedencia | [docs/permisos.md](docs/permisos.md) |
| Migraciones de la base | [docs/migraciones.md](docs/migraciones.md) |
| Respaldos y restauración | [docs/respaldos.md](docs/respaldos.md) |
| Seguridad | [docs/seguridad.md](docs/seguridad.md) |
| Frontend | [frontend/README.md](frontend/README.md) |
| Alcance de red y verificación de tráfico | [README_RED_LOCAL.md](README_RED_LOCAL.md) |
| Evaluación del RAG | [backend/evals/README.md](backend/evals/README.md) |
