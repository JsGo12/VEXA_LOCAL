<#
.SYNOPSIS
  Respaldo cifrado de VEXA. Detiene el servidor si está activo, respalda y lo vuelve a iniciar.

.DESCRIPTION
  -Ejecutar          hace un respaldo ahora en -Destino (y conserva los últimos -Conservar).
  -Programar         registra la tarea semanal "VEXA Respaldo" (domingo 03:00) que ejecuta lo anterior.
  El respaldo solo puede restaurarse con esta misma cuenta de Windows (DPAPI).
  No uses una carpeta de OneDrive ni otra sincronizada con la nube como destino.

.EXAMPLE
  .\respaldo.ps1 -Ejecutar -Destino E:\RespaldosVEXA
.EXAMPLE
  .\respaldo.ps1 -Programar -Destino E:\RespaldosVEXA
#>
param(
    [Parameter(Mandatory = $true)][string]$Destino,
    [switch]$Ejecutar,
    [switch]$Programar,
    [int]$Conservar = 8
)
$ErrorActionPreference = 'Stop'
$codigo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$python = Join-Path $codigo '.venv\Scripts\python.exe'
$dataDir = if ($env:VEXA_DATA_DIR) { $env:VEXA_DATA_DIR } else { Join-Path $env:USERPROFILE '.vexa_local' }
$serverTask = 'VEXA Servidor'

if ($Destino -match 'OneDrive|Dropbox|Google Drive|iCloud') {
    throw 'El destino parece una carpeta sincronizada con la nube. Usa un disco externo o una carpeta local protegida.'
}

if ($Programar) {
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' `
        -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Ejecutar -Destino `"$Destino`" -Conservar $Conservar"
    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At 3am
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries
    Register-ScheduledTask -TaskName 'VEXA Respaldo' -Action $action -Trigger $trigger -Settings $settings `
        -Description 'Respaldo cifrado semanal de VEXA.' -Force | Out-Null
    Write-Host "Tarea 'VEXA Respaldo' registrada (domingos 03:00) hacia $Destino."
    if (-not $Ejecutar) { exit 0 }
}
if (-not $Ejecutar) { throw 'Indica -Ejecutar o -Programar.' }

New-Item -ItemType Directory -Force -Path $Destino | Out-Null
$restart = $false
$info = Join-Path $dataDir 'server.json'
if (Test-Path -LiteralPath $info) {
    $serverPid = (Get-Content -LiteralPath $info -Raw | ConvertFrom-Json).pid
    $proc = Get-Process -Id $serverPid -ErrorAction SilentlyContinue
    if ($proc) {
        Write-Host "Deteniendo el servidor VEXA (PID $serverPid) para un respaldo consistente..."
        # Primero la tarea (para que el Programador no lo reinicie a mitad del respaldo), luego el proceso.
        Stop-ScheduledTask -TaskName $serverTask -ErrorAction SilentlyContinue
        Stop-Process -Id $serverPid -Force -ErrorAction SilentlyContinue
        $proc.WaitForExit(30000) | Out-Null
        $restart = $true
    }
    Remove-Item -LiteralPath $info -ErrorAction SilentlyContinue
}

$file = Join-Path $Destino ("vexa-{0}.vexabackup" -f (Get-Date -Format 'yyyyMMdd-HHmm'))
try {
    & $python (Join-Path $codigo 'backend\scripts\backup_vexa.py') create $file
    if ($LASTEXITCODE -ne 0) { throw "El respaldo falló (código $LASTEXITCODE)." }
    Get-ChildItem -LiteralPath $Destino -Filter 'vexa-*.vexabackup' | Sort-Object LastWriteTime -Descending |
        Select-Object -Skip $Conservar | Remove-Item
}
finally {
    if ($restart -and (Get-ScheduledTask -TaskName $serverTask -ErrorAction SilentlyContinue)) {
        Start-ScheduledTask -TaskName $serverTask
        Write-Host 'Servidor VEXA reiniciado.'
    }
    elseif ($restart) {
        Write-Warning "El servidor estaba activo pero no existe la tarea '$serverTask'; inícialo a mano."
    }
}
Write-Host "Respaldo creado: $file"
