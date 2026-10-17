$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$nodeCommand = Get-Command node -ErrorAction SilentlyContinue
$corepackCommand = Get-Command corepack -ErrorAction SilentlyContinue
if (-not $nodeCommand -or -not $corepackCommand) {
    throw 'Instala Node.js 24 LTS, cierra y vuelve a abrir PowerShell, y repite la compilación. Node incluye Corepack; no hace falta ejecutar corepack enable.'
}
$nodeVersion = [version]((& node --version).TrimStart('v'))
if ($nodeVersion -lt [version]'22.12.0') {
    throw "VEXA requiere Node.js 22.12.0 o posterior; se encontró $nodeVersion. Instala Node.js 24 LTS."
}
$pythonCommand = if ($env:VEXA_PYTHON) { $env:VEXA_PYTHON } else { (Get-Command python -ErrorAction Stop).Source }
$venvPython = Join-Path $PSScriptRoot 'backend/.venv/Scripts/python.exe'
Push-Location $projectRoot
try {
    if (-not (Test-Path -LiteralPath $venvPython)) {
        & $pythonCommand -m venv (Join-Path $PSScriptRoot 'backend/.venv')
    }
    & $venvPython -m pip install -r 'desktop/backend/requirements-build.txt'
    & $venvPython -m PyInstaller `
        --noconfirm `
        --clean `
        --onedir `
        --name VexaBackend `
        --distpath 'desktop/backend/dist' `
        --workpath 'desktop/backend/build' `
        --specpath 'desktop/backend' `
        --add-data "$projectRoot\templates;templates" `
        --add-data "$projectRoot\static;static" `
        --collect-all pdfplumber `
        --collect-all ollama `
        --collect-all docx `
        --collect-all pptx `
        --collect-all openpyxl `
        --collect-all pypdfium2 `
        --collect-all numpy `
        --hidden-import rag_hybrid --hidden-import rag_stages --hidden-import store --hidden-import vault `
        --hidden-import formats --hidden-import model_select --hidden-import watcher `
        web_app.py

    Push-Location (Join-Path $projectRoot 'desktop/electron')
    try {
        corepack pnpm install --frozen-lockfile
        if ($LASTEXITCODE -ne 0) { throw 'Corepack no pudo instalar las dependencias de Electron.' }
        corepack pnpm run dist:win
        if ($LASTEXITCODE -ne 0) { throw 'Falló la creación del instalador NSIS.' }
    }
    finally {
        Pop-Location
    }
}
finally {
    Pop-Location
}
