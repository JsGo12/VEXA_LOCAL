$ErrorActionPreference = 'Stop'
# Empaqueta backend/run.py (Waitress + paquete vexa) con PyInstaller y genera el instalador NSIS de Electron.
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
        --paths "$projectRoot\backend" `
        --add-data "$projectRoot\frontend\templates;templates" `
        --add-data "$projectRoot\frontend\static;static" `
        --collect-submodules vexa `
        --collect-all pdfplumber `
        --collect-all ollama `
        --collect-all docx `
        --collect-all pptx `
        --collect-all openpyxl `
        --collect-all pypdfium2 `
        --collect-all numpy `
        --hidden-import waitress --hidden-import dotenv `
        'backend/run.py'

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
