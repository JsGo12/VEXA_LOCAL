# VEXA Local Desktop

VEXA es un prototipo de escritorio para organizar expedientes jurídicos y consultar sus documentos con asistencia de inteligencia artificial local. Un administrador puede crear cuentas y equipos, asignar casos con fechas límite y cargar documentos. Los abogados acceden a los casos que les corresponden y consultan un chat con fuentes documentales.

El proyecto está pensado para demostración académica. Utilicen documentos ficticios; no carguen expedientes reales ni datos personales.

## Alcance de la versión actual

- La aplicación de Electron inicia el backend Flask en `127.0.0.1` y abre una ventana local.
- Cada computador crea su propia base SQLite y sus propios usuarios, casos y archivos. Los datos no se sincronizan automáticamente entre computadores.
- La asignación a abogados o equipos funciona dentro de una misma instancia local. La colaboración entre instalaciones separadas requeriría un servicio central y sincronización, que no forman parte de esta versión.
- En Windows, los datos se guardan en `%USERPROFILE%\.vexa_local`. La base principal es `vexa_web.db` y los documentos del expediente se almacenan en `case_documents`.
- VEXA cifra el contenido de los documentos almacenados, el historial de chat, los fragmentos indexados, los resúmenes y los vectores semánticos. La base SQLite conserva algunos metadatos operativos, como nombres de usuario, títulos de casos y nombres de archivo, sin cifrado integral.

## Requisitos

- Windows 10 u 11 de 64 bits.
- Python 3 y Node.js LTS para ejecutar desde el código fuente.
- Ollama para las consultas con IA.
- Conexión a Internet durante la configuración para descargar dependencias y modelos.

Descargas oficiales:

- [Python para Windows](https://www.python.org/downloads/windows/)
- [Node.js LTS, incluye npm](https://nodejs.org/en/download/)
- [Ollama para Windows](https://ollama.com/download/windows)

## Preparación de Ollama

Instalen el modelo mínimo de chat:

```powershell
ollama pull llama3.2:1b
ollama list
```

VEXA selecciona entre los modelos de chat instalados según el hardware disponible. Para usar también búsqueda semántica, instalen el modelo de embeddings:

```powershell
ollama pull bge-m3
```

`bge-m3` es opcional: sin él VEXA mantiene la búsqueda léxica BM25, pero no activa la búsqueda por significado. La primera preparación del expediente puede tardar más porque extrae texto y genera o carga los índices. Los fragmentos y vectores se guardan para reutilizarlos en consultas posteriores.

Ollama debe estar iniciado mientras se usa el chat. La memoria necesaria depende de los modelos instalados y del hardware del computador.

## Ejecutar desde el código fuente

Clonen el repositorio y entren a su carpeta:

```powershell
git clone https://github.com/JsGo12/VEXA_LOCAL-Desktop.git
Set-Location .\VEXA_LOCAL-Desktop
```

Instalen las dependencias de Python y de Electron:

```powershell
python -m pip install -r requirements.txt
Set-Location .\desktop\electron
pnpm install --frozen-lockfile
pnpm start
```

El repositorio usa `pnpm-lock.yaml`; usa pnpm y no npm para instalar las dependencias de Electron. Electron abre VEXA en una ventana de escritorio e inicia el backend local. Para ejecutar nuevamente, basta con abrir Ollama y lanzar `pnpm start` desde `desktop\electron`.

## Tipos de archivo y OCR

El administrador puede cargar PDF, DOCX, XLSX, PPTX, TXT y CSV, hasta 30 MB por archivo. La extracción de texto de PDF escaneados requiere instalar Tesseract OCR por separado. Si Windows no encuentra el ejecutable, definan `VEXA_TESSERACT_CMD` con la ruta de `tesseract.exe` antes de iniciar VEXA. Sin Tesseract, los PDF con texto seleccionable y los demás formatos siguen funcionando.

## Carpeta vigilada

Cada caso tiene una carpeta local dentro de `%USERPROFILE%\.vexa_local\carpeta_vigilada\<id_del_caso>`. El administrador puede copiar allí un archivo admitido y VEXA intentará agregarlo al expediente. Al terminar, el original se retira de esa carpeta y se conserva como archivo cifrado dentro de `procesados` o `errores`. La copia asociada al caso también se almacena cifrada en `case_documents`.

## Ejecutar las pruebas

Desde la raíz del repositorio:

```powershell
python -m pytest -q .\desktop\tests
```

Una prueba de OCR puede omitirse si Tesseract no está instalado.

## Crear el instalador de Windows

Desde la raíz del repositorio, ejecuten:

```powershell
powershell -ExecutionPolicy Bypass -File .\desktop\build.ps1
```

El instalador se genera en `desktop\electron\release`. Ollama y los modelos se instalan por separado en cada computador; el instalador de VEXA no los incluye.

## Tecnologías

- Python y Flask para el backend local.
- SQLite para cuentas, equipos, casos y metadatos.
- Electron para la ventana de escritorio.
- HTML, CSS y JavaScript para la interfaz.
- BM25 y embeddings de Ollama para recuperar información documental.
- Ollama para generar respuestas locales con el modelo de chat disponible.

## Respaldo y seguridad

No compartan la carpeta `.vexa_local`, la base de datos ni archivos de casos mediante GitHub. La clave de cifrado de Windows se protege con DPAPI y queda vinculada a la cuenta de Windows del equipo. Si se requiere trasladar los datos a otro computador o usuario, debe planificarse una exportación y migración con descifrado y nuevo cifrado; copiar solo la base y los archivos cifrados no basta.
