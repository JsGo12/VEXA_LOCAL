const { app, BrowserWindow, dialog } = require('electron');
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const net = require('node:net');
const os = require('node:os');
const path = require('node:path');

// Codigo/ (contiene backend/, frontend/, .env)
const projectRoot = path.resolve(__dirname, '..', '..');
let backendProcess = null;   // solo se detiene al salir si lo inició esta ventana
let mainWindow = null;

// Una sola ventana de VEXA por usuario: una segunda ejecución enfoca la existente.
if (!app.requestSingleInstanceLock()) {
  app.quit();
}
app.on('second-instance', () => {
  if (mainWindow) {
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.focus();
  }
});

// Lee una variable de un archivo .env (solo para ubicar la carpeta de datos; no interpreta secretos).
function readEnvValue(file, key) {
  try {
    for (const line of fs.readFileSync(file, 'utf8').split(/\r?\n/)) {
      const match = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/);
      if (match && match[1] === key) return match[2].replace(/^['"]|['"]$/g, '').trim();
    }
  } catch (_) { /* sin .env */ }
  return '';
}

function envFile() {
  if (process.env.VEXA_ENV_FILE) return process.env.VEXA_ENV_FILE;
  return app.isPackaged ? path.join(process.resourcesPath, 'backend', '.env') : path.join(projectRoot, '.env');
}

function dataDir() {
  return process.env.VEXA_DATA_DIR || readEnvValue(envFile(), 'VEXA_DATA_DIR') || path.join(os.homedir(), '.vexa_local');
}

function reserveLocalPort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address();
      server.close(error => error ? reject(error) : resolve(port));
    });
  });
}

// Modo cliente remoto (PCs de abogados): abre el servidor VEXA de la firma por Tailscale sin iniciar
// un backend local. Se activa con VEXA_REMOTE_URL o con <VEXA_DATA_DIR>/cliente.json
// ({"remote_url": "http://100.x.y.z:5000"}), que crea configurar-cliente.ps1.
function isTailscaleOrLocalHost(hostname) {
  const host = hostname.replace(/^\[|\]$/g, '').toLowerCase();
  if (host === 'localhost' || host === '127.0.0.1' || host === '::1') return true;
  if (host.endsWith('.ts.net')) return true;
  const parts = host.split('.').map(Number);
  if (parts.length === 4 && parts.every(n => Number.isInteger(n) && n >= 0 && n <= 255)) {
    return parts[0] === 100 && parts[1] >= 64 && parts[1] <= 127;     // 100.64.0.0/10
  }
  return host.startsWith('fd7a:115c:a1e0:');
}

function remoteOrigin() {
  let raw = process.env.VEXA_REMOTE_URL || '';
  if (!raw) {
    try { raw = JSON.parse(fs.readFileSync(path.join(dataDir(), 'cliente.json'), 'utf8').replace(/^\uFEFF/, '')).remote_url || ''; }
    catch (_) { return null; }
  }
  let url;
  try { url = new URL(raw); } catch (_) { throw new Error(`La dirección del servidor no es válida: ${raw}`); }
  if (!['http:', 'https:'].includes(url.protocol) || !isTailscaleOrLocalHost(url.hostname)) {
    throw new Error('El servidor remoto debe ser una dirección de Tailscale (100.x.y.z o *.ts.net). '
      + 'VEXA no se conecta a servidores públicos.');
  }
  return url.origin;
}

async function isVexaAt(portOrOrigin) {
  const origin = typeof portOrOrigin === 'number' ? `http://127.0.0.1:${portOrOrigin}` : portOrOrigin;
  try {
    const response = await fetch(`${origin}/health`, { signal: AbortSignal.timeout(2500) });
    if (!response.ok) return false;
    const body = await response.json();
    return body && body.app === 'vexa';
  } catch (_) {
    return false;
  }
}

// Si ya hay un servidor VEXA (por ejemplo, Waitress con Tailscale) usando la misma carpeta de datos,
// Electron se conecta a él en lugar de iniciar otro (evita dos carpetas vigiladas sobre la misma base).
async function existingServerPort() {
  try {
    const info = JSON.parse(fs.readFileSync(path.join(dataDir(), 'server.json'), 'utf8'));
    if (Number.isInteger(info.port) && await isVexaAt(info.port)) return info.port;
  } catch (_) { /* no hay servidor activo */ }
  return null;
}

function pythonCommand() {
  if (process.env.VEXA_PYTHON) return process.env.VEXA_PYTHON;
  const venv = path.join(projectRoot, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
  if (fs.existsSync(venv)) return venv;
  return process.platform === 'win32' ? 'python' : 'python3';
}

function startBackend(port) {
  const env = {
    ...process.env,
    VEXA_HOST: '127.0.0.1',
    VEXA_PORT: String(port),
    // El backend embebido usa un puerto aleatorio y solo loopback. El acceso por Tailscale se
    // hace con el servidor Waitress independiente (python backend\run.py).
    TAILSCALE_ENABLED: 'false',
    PYTHONUNBUFFERED: '1',
  };
  if (app.isPackaged) {
    const executable = path.join(process.resourcesPath, 'backend', 'VexaBackend.exe');
    backendProcess = spawn(executable, [], { env, windowsHide: true, stdio: 'ignore' });
  } else {
    backendProcess = spawn(pythonCommand(), [path.join('backend', 'run.py')], {
      cwd: projectRoot, env, windowsHide: true, stdio: 'inherit',
    });
  }
  backendProcess.once('error', error => console.error('No se pudo iniciar el backend de VEXA:', error));
  backendProcess.once('exit', (code, signal) => {
    if (mainWindow && !mainWindow.isDestroyed() && !app.isQuitting) {
      dialog.showErrorBox('VEXA se cerró',
        `El servicio local terminó (código ${code ?? '—'}, señal ${signal ?? '—'}). Vuelve a abrir la aplicación.`);
      app.quit();
    }
  });
}

async function waitForBackend(port, timeoutMs = 60000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (backendProcess && backendProcess.exitCode !== null) {
      if (backendProcess.exitCode === 3) {
        const other = await existingServerPort();
        if (other) { backendProcess = null; return other; }
        throw new Error('Ya hay otro servidor VEXA usando la misma carpeta de datos. Ciérralo y vuelve a intentarlo.');
      }
      if (backendProcess.exitCode === 2) {
        throw new Error('La configuración de VEXA (.env) no es válida. Ejecuta "python backend\\run.py --check" para ver el detalle.');
      }
      throw new Error('El proceso del backend terminó antes de iniciar el servicio.');
    }
    if (await isVexaAt(port)) return port;
    await new Promise(resolve => setTimeout(resolve, 350));
  }
  throw new Error('El servicio local no respondió dentro del tiempo esperado.');
}

function createWindow(portOrOrigin) {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 920,
    minWidth: 1040,
    minHeight: 700,
    show: false,
    autoHideMenuBar: true,
    webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true },
  });
  const localOrigin = typeof portOrOrigin === 'number' ? `http://127.0.0.1:${portOrOrigin}` : portOrOrigin;
  mainWindow.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  mainWindow.webContents.on('will-navigate', (event, targetUrl) => {
    if (!targetUrl.startsWith(`${localOrigin}/`)) event.preventDefault();
  });
  mainWindow.once('ready-to-show', () => mainWindow.show());
  mainWindow.on('closed', () => { mainWindow = null; });
  return mainWindow.loadURL(localOrigin);
}

async function waitForRemote(origin, timeoutMs = 20000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await isVexaAt(origin)) return origin;
    await new Promise(resolve => setTimeout(resolve, 1000));
  }
  throw new Error(`No se pudo conectar con el servidor VEXA en ${origin}. Comprueba que Tailscale esté `
    + 'conectado en este equipo y que el servidor de la firma esté encendido.');
}

app.whenReady().then(async () => {
  try {
    const remote = remoteOrigin();
    if (remote) {
      await createWindow(await waitForRemote(remote));
      return;
    }
    let port = await existingServerPort();
    if (!port) {
      port = await reserveLocalPort();
      startBackend(port);
      port = await waitForBackend(port);
    }
    await createWindow(port);
  } catch (error) {
    dialog.showErrorBox('No se pudo iniciar VEXA', error.message);
    app.quit();
  }
});

app.on('before-quit', () => {
  app.isQuitting = true;
  if (backendProcess && backendProcess.exitCode === null) {
    backendProcess.kill();
    try { fs.unlinkSync(path.join(dataDir(), 'server.json')); } catch (_) { /* ya no existe */ }
  }
});

app.on('window-all-closed', () => app.quit());
