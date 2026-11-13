$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
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
        web_app.py

    Push-Location (Join-Path $projectRoot 'desktop/electron')
    try {
        if (Get-Command npm -ErrorAction SilentlyContinue) {
            npm install
            npm run dist:win
        }
        elseif (Get-Command pnpm -ErrorAction SilentlyContinue) {
            pnpm install
            pnpm run dist:win
        }
        else {
            throw 'Instala Node.js (que incluye npm) o pnpm para compilar Electron.'
        }
    }
    finally {
        Pop-Location
    }
}
finally {
    Pop-Location
}
