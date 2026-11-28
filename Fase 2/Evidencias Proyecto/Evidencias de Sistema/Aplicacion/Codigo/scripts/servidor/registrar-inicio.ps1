<#
.SYNOPSIS
  Registra la tarea programada "VEXA Servidor": inicia VEXA (Waitress) al iniciar sesión el
  administrador, la reinicia si se cae y evita que Windows suspenda el equipo con corriente.

.DESCRIPTION
  La tarea se ejecuta con la cuenta actual (necesario: la clave de cifrado está protegida con DPAPI
  para esta cuenta de Windows) y solo cuando la sesión está iniciada. No requiere permisos de
  administrador, salvo -SinSuspension, que cambia el plan de energía.

.EXAMPLE
  .\registrar-inicio.ps1
.EXAMPLE
  .\registrar-inicio.ps1 -SinSuspension
.EXAMPLE
  .\registrar-inicio.ps1 -Quitar
#>
param([switch]$SinSuspension, [switch]$Quitar)
$ErrorActionPreference = 'Stop'
$taskName = 'VEXA Servidor'

if ($Quitar) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Tarea '$taskName' eliminada."
    exit 0
}

$runner = Join-Path $PSScriptRoot 'ejecutar-servidor.ps1'
$codigo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$python = Join-Path $codigo '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw "No existe $python. Instala primero las dependencias (docs/ejecucion.md)." }

& $python (Join-Path $codigo 'backend\run.py') --check
if ($LASTEXITCODE -ne 0) { throw 'La configuración (.env) no es válida; corrígela antes de registrar la tarea.' }

$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$runner`"" -WorkingDirectory $codigo
# Espera 60 s tras el inicio de sesión para que Tailscale obtenga su IP.
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$trigger.Delay = 'PT60S'
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings `
    -Principal $principal -Description 'Servidor local de VEXA (Waitress, solo loopback/Tailscale).' -Force | Out-Null
Write-Host "Tarea '$taskName' registrada. Iníciala ahora con: Start-ScheduledTask -TaskName '$taskName'"

if ($SinSuspension) {
    powercfg /change standby-timeout-ac 0
    powercfg /change hibernate-timeout-ac 0
    Write-Host 'Suspensión e hibernación desactivadas con el equipo conectado a la corriente.'
}
Write-Host 'Recuerda: Ollama debe iniciar con Windows (opción por defecto de su instalador).'
