const { app, BrowserWindow, dialog } = require('electron');
const { spawn } = require('node:child_process');
const net = require('node:net');
const path = require('node:path');

const projectRoot = path.resolve(__dirname, '..', '..');
let backendProcess = null;
let mainWindow = null;
let backendPort = null;

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

function startBackend(port) {
  const env = {
    ...process.env,
    VEXA_HOST: '127.0.0.1',
    VEXA_PORT: String(port),
    PYTHONUNBUFFERED: '1',
  };

  if (app.isPackaged) {
    const executable = path.join(process.resourcesPath, 'backend', 'VexaBackend.exe');
    backendProcess = spawn(executable, [], { env, windowsHide: true, stdio: 'ignore' });
  } else {
    const python = process.env.VEXA_PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
    backendProcess = spawn(python, ['web_app.py'], {
      cwd: projectRoot,
      env,
      windowsHide: true,
      stdio: 'inherit',
    });
  }

  backendProcess.once('error', error => {
    console.error('No se pudo iniciar el backend de VEXA:', error);
  });
  backendProcess.once('exit', (code, signal) => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      dialog.showErrorBox(
        'VEXA se cerró',
        `El servicio local terminó (código ${code ?? '—'}, señal ${signal ?? '—'}). Vuelve a abrir la aplicación.`,
      );
      app.quit();
    }
  });
}

async function waitForBackend(port, timeoutMs = 45000) {
  const deadline = Date.now() + timeoutMs;
  const healthUrl = `http://127.0.0.1:${port}/health`;
  while (Date.now() < deadline) {
    if (backendProcess && backendProcess.exitCode !== null) {
      throw new Error('El proceso Python terminó antes de iniciar el servicio.');
    }
    try {
      const response = await fetch(healthUrl, { signal: AbortSignal.timeout(1200) });
      if (response.ok) return;
    } catch (_) {
      // Flask aún está iniciando; volver a comprobar brevemente.
    }
    await new Promise(resolve => setTimeout(resolve, 350));
  }
  throw new Error('El servicio local no respondió dentro del tiempo esperado.');
}

function createWindow(port) {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 920,
    minWidth: 1040,
    minHeight: 700,
    show: false,
    autoHideMenuBar: true,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  const localOrigin = `http://127.0.0.1:${port}`;
  mainWindow.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  mainWindow.webContents.on('will-navigate', (event, targetUrl) => {
    if (!targetUrl.startsWith(`${localOrigin}/`)) event.preventDefault();
  });
  mainWindow.once('ready-to-show', () => mainWindow.show());
  mainWindow.on('closed', () => { mainWindow = null; });
  return mainWindow.loadURL(localOrigin);
}

app.whenReady().then(async () => {
  try {
    backendPort = await reserveLocalPort();
    startBackend(backendPort);
    await waitForBackend(backendPort);
    await createWindow(backendPort);
  } catch (error) {
    dialog.showErrorBox('No se pudo iniciar VEXA', error.message);
    app.quit();
  }
});

app.on('before-quit', () => {
  if (backendProcess && backendProcess.exitCode === null) backendProcess.kill();
});

app.on('window-all-closed', () => app.quit());
