# VEXA_LOCAL-Desktop

Aplicación de escritorio local para organizar expedientes jurídicos y consultar sus documentos con asistencia de IA. El administrador asigna expedientes a abogados o equipos; cada abogado consulta solo los casos autorizados. La respuesta del chat se genera con Ollama y se muestra progresivamente.

> Proyecto académico en desarrollo. Para demostraciones, usen documentos sintéticos; no carguen expedientes reales ni datos personales.

## Requisitos

- Windows 10 u 11 de 64 bits.
- Python 3 y Node.js LTS para ejecutar desde el código fuente.
- Ollama y el modelo `llama3.2:1b` para usar el chat con IA.
- Conexión a Internet para descargar los instaladores, paquetes y modelo durante la configuración.

Descargas oficiales:

- [Python para Windows](https://www.python.org/downloads/windows/)
- [Node.js LTS (incluye npm)](https://nodejs.org/en/download/)
- [Ollama para Windows](https://ollama.com/download/windows)

## Ejecutar VEXA desde el código fuente

### 1. Instalar los programas

Instalen Python y Node.js usando sus instaladores oficiales y acepten las opciones predeterminadas. Instalen Ollama y manténganlo disponible mientras usan el chat.

Después de instalar Python y Node.js, cierren y vuelvan a abrir VS Code. En una terminal PowerShell comprueben que los comandos estén disponibles:

```powershell
python --version
node -v
npm -v
```

### 2. Descargar el modelo de IA

En PowerShell ejecuten:

```powershell
ollama pull llama3.2:1b
ollama list
```

Confirmen que `llama3.2:1b` aparezca en la lista. La primera descarga requiere Internet y espacio adicional en disco.

### 3. Instalar dependencias e iniciar la aplicación

Clonen o descarguen este repositorio y, desde su carpeta raíz, ejecuten:

```powershell
python -m pip install -r requirements.txt
Set-Location .\desktop\electron
npm install
npm start
```

Electron abrirá VEXA en una ventana de escritorio e iniciará el backend local automáticamente. Para las consultas con IA, Ollama debe estar iniciado y el modelo descargado.

## Crear el instalador de Windows

Desde la carpeta raíz del repositorio, ejecuten:

```powershell
powershell -ExecutionPolicy Bypass -File .\desktop\build.ps1
```

El instalador se genera en `desktop\electron\release`. La compilación requiere Python, Node.js/npm y conexión a Internet para instalar dependencias. Ollama y `llama3.2:1b` se instalan por separado también en el computador donde se use VEXA.

## Tecnologías

- Python, Flask y SQLite para el backend local.
- Electron para la ventana de escritorio.
- HTML, CSS y JavaScript para la interfaz.
- BM25 para recuperar fragmentos documentales.
- Ollama con `llama3.2:1b` para generar respuestas locales.

## Solución de problemas

- **`npm` no se reconoce:** instala Node.js LTS, cierra y vuelve a abrir VS Code y comprueba `npm -v`.
- **Ollama o el modelo no responde:** inicia Ollama y comprueba con `ollama list` que exista `llama3.2:1b`.
- **No se inicia el backend:** comprueba que Python esté instalado y que `python --version` funcione; vuelve a instalar las dependencias con `python -m pip install -r requirements.txt`.

## Datos locales

Las cuentas, expedientes y documentos de prueba se guardan localmente en el computador. No compartan bases de datos, archivos de expedientes ni información personal mediante GitHub.
