<#
.SYNOPSIS
  Ejecuta el servidor VEXA (Waitress) y guarda su salida en <VEXA_DATA_DIR>\logs.
  Lo usa la tarea programada "VEXA Servidor" (registrar-inicio.ps1); también puede ejecutarse a mano.
#>
$ErrorActionPreference = 'Stop'
$codigo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$python = Join-Path $codigo '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw "No existe $python. Crea el entorno: python -m venv .venv" }
$dataDir = if ($env:VEXA_DATA_DIR) { $env:VEXA_DATA_DIR } else { Join-Path $env:USERPROFILE '.vexa_local' }
$logDir = Join-Path $dataDir 'logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir ("servidor-{0}.log" -f (Get-Date -Format 'yyyyMMdd'))

# Conserva 30 días de registros.
Get-ChildItem -LiteralPath $logDir -Filter 'servidor-*.log' |
    Where-Object LastWriteTime -lt (Get-Date).AddDays(-30) | Remove-Item -ErrorAction SilentlyContinue

Set-Location $codigo
& $python (Join-Path $codigo 'backend\run.py') *>> $log
exit $LASTEXITCODE
