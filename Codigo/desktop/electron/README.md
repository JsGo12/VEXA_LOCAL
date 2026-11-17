# VEXA Desktop con Electron

`main.js`:

1. Garantiza una sola ventana de VEXA (`requestSingleInstanceLock`).
2. Si ya hay un servidor VEXA activo con la misma carpeta de datos (lee `<VEXA_DATA_DIR>\server.json` y comprueba `/health`), se conecta a él y no inicia otro.
3. Si no, reserva un puerto libre en `127.0.0.1` y ejecuta `backend\run.py` (Waitress) con `VEXA_HOST=127.0.0.1`, ese puerto y `TAILSCALE_ENABLED=false`. Usa el Python de `Codigo\.venv`, el de `VEXA_PYTHON` o `python` del PATH. Empaquetado: `resources\backend\VexaBackend.exe`, sin ventana de consola.
4. Espera `/health` (hasta 60 s) y abre la interfaz. Bloquea navegación fuera del origen local y ventanas emergentes; `contextIsolation` y `sandbox` activos, sin `nodeIntegration`.
5. Al salir detiene solo el servidor que inició él.

Si el backend termina con código 2 (configuración inválida) o 3 (otro servidor activo), muestra un mensaje explicativo.

## Modo cliente remoto (PCs de abogados)

Si existe `VEXA_REMOTE_URL` o `%USERPROFILE%\.vexa_local\cliente.json` (`{"remote_url": "http://100.x.y.z:5000"}`), la app **no inicia un backend local**: comprueba `/health` del servidor de la firma y lo abre. Solo admite direcciones de Tailscale (`100.64.0.0/10`, `*.ts.net`) o loopback. Configúralo con:

```powershell
.\configurar-cliente.ps1 -Url http://100.x.y.z:5000 -AccesoDirecto   # -Quitar para volver al modo local
```

## Desarrollo

Desde `Codigo/`, con las dependencias de Python instaladas (ver [docs/ejecucion.md](../../docs/ejecucion.md)):

```powershell
Set-Location .\desktop\electron
.\setup-dev.ps1          # primera vez: Corepack prepara pnpm, instala desde pnpm-lock.yaml y abre VEXA
corepack pnpm start      # siguientes veces
```

No hace falta instalar pnpm globalmente ni ejecutar `corepack enable`. Repite `corepack pnpm install --frozen-lockfile` si cambian `package.json` o `pnpm-lock.yaml`.

## Instalador

```powershell
powershell -ExecutionPolicy Bypass -File .\desktop\build.ps1
```

Genera el instalador NSIS en `desktop\electron\release`. Ollama y los modelos se instalan aparte. Para configurar el backend instalado, coloca un `.env` junto a `VexaBackend.exe` (`resources\backend`) o en `%USERPROFILE%\.vexa_local\.env`.

## Acceso remoto

Electron nunca expone VEXA fuera del equipo. Para acceso desde otros dispositivos usa el servidor independiente con Tailscale ([docs/tailscale.md](../../docs/tailscale.md)); si ese servidor está activo, Electron se conecta a él.
