<#
.SYNOPSIS
  Configura un PC de abogado para usar el servidor VEXA de la firma por Tailscale.

.DESCRIPTION
  - Comprueba que la dirección sea de Tailscale (100.64.0.0/10 o *.ts.net) y que el servidor responda.
  - Guarda %USERPROFILE%\.vexa_local\cliente.json: con ese archivo, la app de escritorio VEXA abre el
    servidor remoto en vez de iniciar un backend local.
  - Con -AccesoDirecto crea además un acceso directo en el Escritorio para abrir VEXA en el navegador.
  - Con -Quitar elimina la configuración (la app vuelve al modo local).
  No guarda contraseñas ni datos de casos en este equipo.

.EXAMPLE
  .\configurar-cliente.ps1 -Url http://100.101.102.103:5000 -AccesoDirecto
.EXAMPLE
  .\configurar-cliente.ps1 -Quitar
#>
param(
    [string]$Url,
    [switch]$AccesoDirecto,
    [switch]$Quitar
)
$ErrorActionPreference = 'Stop'
$dataDir = if ($env:VEXA_DATA_DIR) { $env:VEXA_DATA_DIR } else { Join-Path $env:USERPROFILE '.vexa_local' }
$configPath = Join-Path $dataDir 'cliente.json'
$shortcut = Join-Path ([Environment]::GetFolderPath('Desktop')) 'VEXA (servidor de la firma).url'

if ($Quitar) {
    Remove-Item -LiteralPath $configPath -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $shortcut -ErrorAction SilentlyContinue
    Write-Host 'Configuración de cliente eliminada.'
    exit 0
}
if (-not $Url) { throw 'Indica la dirección del servidor, por ejemplo: -Url http://100.101.102.103:5000' }

try { $uri = [Uri]$Url } catch { throw "La dirección no es válida: $Url" }
if ($uri.Scheme -notin @('http', 'https')) { throw 'La dirección debe empezar por http:// o https://' }
$hostName = $uri.Host.ToLowerInvariant()
$isTailscale = $hostName.EndsWith('.ts.net')
$ip = $null
if ([System.Net.IPAddress]::TryParse($hostName, [ref]$ip) -and $ip.AddressFamily -eq 'InterNetwork') {
    $b = $ip.GetAddressBytes()
    $isTailscale = ($b[0] -eq 100 -and $b[1] -ge 64 -and $b[1] -le 127)
}
if (-not $isTailscale) {
    throw 'Solo se admiten direcciones de Tailscale (100.x.y.z o nombre *.ts.net). VEXA no usa servidores públicos.'
}

$tailscale = Get-Command tailscale -ErrorAction SilentlyContinue
if (-not $tailscale -and (Test-Path 'C:\Program Files\Tailscale\tailscale.exe')) { $tailscale = 'C:\Program Files\Tailscale\tailscale.exe' }
if (-not $tailscale) { Write-Warning 'No se encontró Tailscale en este equipo. Instálalo e inicia sesión antes de usar VEXA.' }

$origin = $uri.GetLeftPart([UriPartial]::Authority)
try {
    $health = Invoke-RestMethod -Uri "$origin/health" -TimeoutSec 8
    if ($health.app -ne 'vexa') { throw 'respuesta inesperada' }
    Write-Host "Servidor VEXA encontrado en $origin."
}
catch {
    Write-Warning "No se pudo contactar el servidor en $origin. Revisa que Tailscale esté conectado y el servidor encendido. La configuración se guarda igual."
}

New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
$json = @{ remote_url = $origin } | ConvertTo-Json
[System.IO.File]::WriteAllText($configPath, $json, (New-Object System.Text.UTF8Encoding $false))
Write-Host "Guardado $configPath. La app de escritorio VEXA abrirá $origin."

if ($AccesoDirecto) {
    "[InternetShortcut]`r`nURL=$origin/`r`n" | Set-Content -LiteralPath $shortcut -Encoding ascii
    Write-Host "Acceso directo creado en el Escritorio: $shortcut"
}
