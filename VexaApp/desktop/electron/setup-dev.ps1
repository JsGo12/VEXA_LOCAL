$ErrorActionPreference = 'Stop'

function Stop-WithHint([string]$message) {
    Write-Error $message
    exit 1
}

$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) {
    Stop-WithHint 'No se encontró Node.js. Instala Node.js 24 LTS y vuelve a abrir PowerShell.'
}

try {
    $nodeVersion = [version]((& node --version).TrimStart('v'))
}
catch {
    Stop-WithHint 'No se pudo leer la versión de Node.js. Reinstala Node.js 24 LTS y abre una terminal nueva.'
}
if ($nodeVersion -lt [version]'22.12.0') {
    Stop-WithHint "VEXA requiere Node.js 22.12.0 o posterior; se encontró $nodeVersion. Instala Node.js 24 LTS."
}

if (-not (Get-Command corepack -ErrorAction SilentlyContinue)) {
    Stop-WithHint 'No se encontró Corepack. Reinstala Node.js 24 LTS y abre una terminal nueva; no hace falta ejecutar corepack enable.'
}

Push-Location $PSScriptRoot
try {
    Write-Host 'Corepack usará la versión de pnpm fijada por package.json.'
    & corepack pnpm --version
    if ($LASTEXITCODE -ne 0) { throw 'Corepack no pudo preparar pnpm.' }
    & corepack pnpm install --frozen-lockfile
    if ($LASTEXITCODE -ne 0) { throw 'No se pudieron instalar las dependencias de Electron.' }
    & corepack pnpm start
    if ($LASTEXITCODE -ne 0) { throw 'VEXA terminó con un error.' }
}
finally {
    Pop-Location
}
