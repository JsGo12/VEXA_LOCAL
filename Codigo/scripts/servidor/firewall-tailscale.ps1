<#
.SYNOPSIS
  Permite conexiones entrantes al puerto de VEXA SOLO desde la interfaz y el rango de Tailscale.
  Ejecutar en PowerShell como administrador.

.EXAMPLE
  .\firewall-tailscale.ps1            # puerto 5000
  .\firewall-tailscale.ps1 -Puerto 5443
  .\firewall-tailscale.ps1 -Quitar
#>
param([int]$Puerto = 5000, [switch]$Quitar)
$ErrorActionPreference = 'Stop'
$name = 'VEXA (solo Tailscale)'

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { throw 'Abre PowerShell como administrador para modificar el firewall.' }

Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue | Remove-NetFirewallRule
if ($Quitar) { Write-Host "Regla '$name' eliminada."; exit 0 }

$iface = Get-NetAdapter -ErrorAction SilentlyContinue | Where-Object { $_.InterfaceDescription -like '*Tailscale*' -or $_.Name -like '*Tailscale*' } | Select-Object -First 1
if (-not $iface) { throw 'No se encontró el adaptador de Tailscale. Instala Tailscale e inicia sesión.' }

New-NetFirewallRule -DisplayName $name -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Puerto `
    -InterfaceAlias $iface.Name -RemoteAddress '100.64.0.0/10' -Profile Any `
    -Description 'Acceso a VEXA solo desde dispositivos de la red Tailscale.' | Out-Null
Write-Host "Regla '$name' creada: TCP $Puerto, interfaz '$($iface.Name)', origen 100.64.0.0/10."
Write-Host 'Si Windows preguntó antes por python.exe en redes públicas, deniega esa opción.'
