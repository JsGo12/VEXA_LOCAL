# Acceso privado con Tailscale

Tailscale crea una red privada cifrada (WireGuard) entre dispositivos de tu organización. VEXA puede escuchar **además** en la IP de Tailscale del equipo servidor para que el abogado jefe u otros usuarios autorizados entren desde sus propios equipos, sin publicar VEXA en Internet.

```text
Equipo servidor                                   Dispositivos autorizados
┌──────────────────────────────┐   WireGuard   ┌────────────────────────┐
│ Waitress 127.0.0.1:5000      │◄─────────────►│ Navegador → 100.x:5000 │
│ Waitress 100.x.y.z:5000      │  (tailnet)    └────────────────────────┘
│ SQLite · documentos cifrados │
│ Ollama 127.0.0.1:11434       │
└──────────────────────────────┘
```

## Qué es privado y qué no

- **No sale del servidor:** documentos, fragmentos, prompts, respuestas y la base. Ollama solo escucha en loopback y VEXA rechaza un `OLLAMA_HOST` externo.
- **Sí hay comunicación externa de Tailscale:** el cliente habla con el servidor de coordinación de Tailscale (claves públicas, metadatos de los dispositivos) y, si no logra conexión directa, el tráfico **cifrado** puede pasar por relays DERP. Los relays no pueden leerlo, pero ven que hay tráfico. Tailscale **no equivale a cero conexiones externas**.
- **No se usa:** Tailscale Funnel, `tailscale serve` hacia Internet, ngrok, port forwarding ni `0.0.0.0`.

## 1. Instalar y conectar

En el servidor y en cada dispositivo autorizado:

1. Instala Tailscale: <https://tailscale.com/download/windows>.
2. Inicia sesión con la cuenta de la organización (`tailscale up` o desde el icono de la bandeja).
3. En el servidor, anota su IP: `tailscale ip -4` (empieza por `100.`).

## 2. Autorizar dispositivos

En la consola de administración (<https://login.tailscale.com/admin/machines>):

- Activa **Device approval** (*Settings → Device management*) para que cada equipo nuevo requiera aprobación manual.
- Aprueba solo los equipos de la firma; desactiva **key expiry** únicamente en el servidor si necesitas que no caduque.
- Elimina los dispositivos que dejen de usarse.

## 3. Restringir el acceso con ACL

Por defecto todos los dispositivos de una tailnet se ven entre sí. Limita quién llega al puerto de VEXA con una política (*Access controls*), por ejemplo:

```jsonc
{
  "tagOwners": { "tag:vexa-server": ["autogroup:admin"] },
  "groups":    { "group:vexa-users": ["jefa@estudio.cl", "abogado@estudio.cl"] },
  "acls": [
    { "action": "accept", "src": ["group:vexa-users"], "dst": ["tag:vexa-server:5000"] }
  ]
}
```

Asigna la etiqueta `tag:vexa-server` al equipo servidor. Con esta política solo los integrantes de `group:vexa-users` pueden abrir el puerto 5000 del servidor; cualquier otro tráfico hacia él queda bloqueado por Tailscale. **Las ACL de Tailscale no reemplazan las cuentas de VEXA**: cada persona sigue necesitando su usuario y sus permisos.

## 4. Configurar VEXA

En `Codigo/.env` del servidor:

```dotenv
TAILSCALE_ENABLED=true
TAILSCALE_BIND_ADDRESS=100.x.y.z      # vacío = detección automática con `tailscale ip -4`
TAILSCALE_PORT=5000                   # opcional
TAILSCALE_HOST=servidor-vexa.tu-red.ts.net   # opcional, si usas el nombre MagicDNS
```

Comprueba y arranca el servidor independiente (Electron nunca abre Tailscale por sí mismo):

```powershell
.\.venv\Scripts\python.exe backend\run.py --check
.\.venv\Scripts\python.exe backend\run.py
```

Verás `escuchando en: http://127.0.0.1:5000, http://100.x.y.z:5000`. Desde un dispositivo autorizado abre `http://100.x.y.z:5000` (o `http://servidor-vexa.tu-red.ts.net:5000`).

### Por qué se escucha en la IP de Tailscale y no en 0.0.0.0

Waitress recibe dos direcciones explícitas (`127.0.0.1:5000 100.x.y.z:5000`). Así el puerto **no existe** en la interfaz Wi-Fi/Ethernet ni en otras redes. Si Tailscale aún no tiene IP al arrancar, VEXA no inicia (no cae a `0.0.0.0`). Además, cada petición pasa por un filtro que rechaza orígenes fuera de loopback y de `100.64.0.0/10` / `fd7a:115c:a1e0::/48`, y Flask solo acepta los nombres de host configurados.

## 5. Firewall de Windows

La primera vez, Windows puede preguntar si permite a `python.exe` aceptar conexiones. Elige **solo redes privadas** o crea una regla limitada a la interfaz de Tailscale:

```powershell
New-NetFirewallRule -DisplayName "VEXA (solo Tailscale)" -Direction Inbound -Protocol TCP `
  -LocalPort 5000 -InterfaceAlias "Tailscale" -RemoteAddress 100.64.0.0/10 -Action Allow
```

No crees reglas para redes públicas ni abras el puerto en el router.

## 6. HTTPS opcional dentro de la tailnet

El tráfico ya va cifrado por WireGuard. Si además quieres HTTPS con certificado válido, `tailscale serve --bg 5000` publica VEXA **solo dentro de la tailnet** (no es Funnel). En ese caso deja `TAILSCALE_ENABLED=false` (Tailscale reenvía a `127.0.0.1`), define `TAILSCALE_HOST` con el nombre MagicDNS y `VEXA_SESSION_COOKIE_SECURE=true`. **Nunca ejecutes `tailscale funnel`.**

## Comprobaciones

```powershell
Get-NetTCPConnection -State Listen -LocalPort 5000 | Select-Object LocalAddress, LocalPort
```

Debe mostrar solo `127.0.0.1` y la IP `100.x`. Desde un equipo **fuera** de la tailnet la conexión a la IP de la red local debe fallar.
