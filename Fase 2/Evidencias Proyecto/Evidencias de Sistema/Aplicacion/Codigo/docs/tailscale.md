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

## 6. HTTPS opcional dentro de la tailnet (`tailscale serve`)

Entre equipos de la tailnet el tráfico ya va cifrado por WireGuard. HTTPS agrega además un certificado válido: el navegador muestra el candado, la cookie de sesión se marca `Secure` y VEXA deja de escuchar en la IP 100.x (solo en `127.0.0.1`, detrás de Tailscale). Es opcional y se revierte en un minuto. **`tailscale serve` publica solo dentro de la tailnet; nunca uses `tailscale funnel`, que lo abriría a Internet.**

> **Privacidad del nombre:** los certificados HTTPS quedan en registros públicos (Certificate Transparency). El nombre del equipo y de la tailnet (`vexa-servidor.tu-red.ts.net`) se vuelve visible en Internet, aunque nadie de afuera pueda conectarse. Si eso importa, renombra el equipo en Tailscale con un nombre neutro antes de activarlo.

**Paso 1 — Activar HTTPS en Tailscale (una vez).** En el panel de Tailscale → **DNS**: activa **MagicDNS** y, más abajo, **HTTPS Certificates**.

**Paso 2 — Publicar VEXA en la tailnet.** En el PC servidor (PowerShell):

```powershell
tailscale serve --bg 5000
tailscale serve status        # debe mostrar https://<equipo>.<tu-red>.ts.net  →  proxy http://127.0.0.1:5000
```

Si `status` dice algo de **Funnel**, ejecuta `tailscale funnel reset` de inmediato.

**Paso 3 — Ajustar el `.env` del servidor** y reiniciar VEXA (tarea programada o `backend\run.py`):

```ini
TAILSCALE_ENABLED=false                         # VEXA escucha solo en 127.0.0.1; Tailscale reenvía
TAILSCALE_HOST=<equipo>.<tu-red>.ts.net         # el nombre que muestra `tailscale serve status`
VEXA_SESSION_COOKIE_SECURE=true                 # la cookie de sesión solo viaja por HTTPS
```

**Paso 4 — Clientes.** En cada PC de abogado: `configurar-cliente.ps1 -Url https://<equipo>.<tu-red>.ts.net`. En el navegador, usa esa misma dirección (la antigua `http://100.x:5000` deja de responder).

**Paso 5 — ACL y firewall.** En la ACL del punto 3, cambia el puerto de destino a `tag:vexa-server:443`. La regla del firewall de Windows para el puerto 5000 ya no hace falta: puedes deshabilitarla.

**Comprobar:** `Get-NetTCPConnection -State Listen -LocalPort 5000` debe mostrar solo `127.0.0.1`. Al abrir `https://<equipo>.<tu-red>.ts.net` el navegador muestra el candado; desde un equipo fuera de la tailnet la dirección no responde. En el PC servidor también puedes seguir usando `http://127.0.0.1:5000`; si el inicio de sesión no se mantiene ahí (por la cookie `Secure`), entra por la dirección `https://`.

**Revertir:** `tailscale serve reset`, vuelve el `.env` a `TAILSCALE_ENABLED=true` y `VEXA_SESSION_COOKIE_SECURE=false`, reinicia VEXA y reconfigura los clientes con `http://100.x:5000`.

**Docker:** el mismo paso 2 dentro del contenedor (`docker compose exec tailscale tailscale serve --bg 5000`); en `.env.docker`, `TAILSCALE_HOST` y `VEXA_SESSION_COOKIE_SECURE=true`. Ahí VEXA sigue escuchando también en la IP del contenedor, que solo es alcanzable dentro de la tailnet.

## Comprobaciones

```powershell
Get-NetTCPConnection -State Listen -LocalPort 5000 | Select-Object LocalAddress, LocalPort
```

Debe mostrar solo `127.0.0.1` y la IP `100.x`. Desde un equipo **fuera** de la tailnet la conexión a la IP de la red local debe fallar.
