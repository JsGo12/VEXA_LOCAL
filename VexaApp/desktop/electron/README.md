# VEXA Desktop con Electron

Electron inicia el backend Flask en una dirección local (`127.0.0.1`), espera a que responda `/health` y carga la interfaz en una ventana nativa. Al cerrar la aplicación, detiene el proceso Python.

## Ejecutar en modo desarrollo

Antes de empezar, instala Node.js 24 LTS y Python 3. Las versiones de las herramientas de Electron se fijan en `package.json` y `pnpm-lock.yaml`.

Desde PowerShell en la raíz del repositorio, instala los requisitos de Python y arranca el entorno de desarrollo:

```powershell
python -m pip install -r requirements.txt
Set-Location .\desktop\electron
.\setup-dev.ps1
```

El script comprueba Node.js y Corepack, prepara la versión de pnpm fijada para el proyecto, instala respetando `pnpm-lock.yaml` y abre VEXA. Corepack no requiere instalar el comando global `pnpm` ni ejecutar `corepack enable`, que puede fallar por permisos en `C:\Program Files`.

En los siguientes inicios, abre PowerShell en `desktop\electron` y ejecuta `corepack pnpm start`. Repite `corepack pnpm install --frozen-lockfile` si cambian `package.json` o `pnpm-lock.yaml`.

Requisitos adicionales: Ollama iniciado con al menos un modelo de conversación instalado. `bge-m3` habilita la búsqueda semántica y es opcional; si falta, VEXA conserva BM25.

Si Python no está en `PATH`, define `VEXA_PYTHON` con la ruta del ejecutable de Python antes de iniciar Electron.

## Crear el instalador

Desde la raíz del repositorio:

```powershell
powershell -ExecutionPolicy Bypass -File .\desktop\build.ps1
```

El script crea un entorno aislado en `desktop/backend/.venv`, empaqueta el backend y genera el instalador NSIS en `desktop/electron/release`. Ollama y sus modelos no se incluyen.

## Datos locales y seguridad

Los datos se guardan en `%USERPROFILE%\.vexa_local`. El backend de Electron escucha solo en `127.0.0.1`; cada instalación mantiene su propia base y no sincroniza casos con otros computadores. La ventana mantiene `contextIsolation` y `sandbox` habilitados, con `nodeIntegration` deshabilitado.
