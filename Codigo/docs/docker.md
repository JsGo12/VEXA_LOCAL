# VEXA en Docker

Alternativa al servidor Windows de [despliegue.md](despliegue.md). Archivos: `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `.env.docker.example`.

## Diseño (por qué así)

```text
┌──────────── red del contenedor «tailscale» (compartida) ────────────┐
│  tailscale  →  interfaz tailscale0 con IP 100.x (nodo «vexa-servidor») │
│  vexa       →  escucha en 127.0.0.1:5000 y 100.x:5000                  │
│  ollama     →  escucha SOLO en 127.0.0.1:11434                         │
└──────────────────────────────────────────────────────────────────────┘
        sin «ports:»: nada se publica en la red local del equipo
```

- Se mantiene la política de red de VEXA: `VEXA_HOST` y `OLLAMA_HOST` siguen siendo loopback y el segundo listener es solo la IP de Tailscale. **No se usa `0.0.0.0` ni se publican puertos.**
- VEXA no tiene la CLI de Tailscale: detecta la IP en la interfaz `tailscale0` (solo interfaces llamadas `tailscale…`, para no confundirla con una IP CGNAT del proveedor).
- La imagen de Ollama escucha en `0.0.0.0` por defecto; el compose lo fuerza a `127.0.0.1` para que no quede expuesto en Tailscale.
- La imagen no lleva `.env`, datos, pruebas ni entornos locales (`.dockerignore`). Corre con un usuario sin privilegios.

## ⚠️ Diferencias de seguridad con el servidor Windows

1. **Sin DPAPI.** En Linux no existe DPAPI: `vault.key` y `web_secret.key` quedan en el volumen `vexa_datos` con permisos `600`, sin la protección de la cuenta de Windows. Quien tenga acceso al Docker del equipo puede leer la clave. Protege el equipo y los respaldos del volumen.
2. **Los datos de Windows no se pueden reutilizar.** La `vault.key` de `%USERPROFILE%\.vexa_local` está cifrada con DPAPI y la base guarda rutas de Windows. **No montes esa carpeta en el contenedor.** El contenedor empieza con una base vacía y su propio administrador.
3. Es otro nodo de Tailscale (`vexa-servidor`) con su propia IP 100.x: los PCs de abogados deben apuntar a esa IP, no a la del PC anfitrión.

## Uso

Requisitos: Docker Desktop (backend WSL 2) en el PC servidor.

```powershell
Set-Location Codigo
Copy-Item .env.docker.example .env.docker      # opcional: modelo, MagicDNS…
docker compose up -d --build
docker compose logs -f tailscale               # 1.ª vez: abre el enlace "To authenticate, visit…"
docker compose exec tailscale tailscale ip -4  # IP 100.x para los clientes
docker compose exec ollama ollama pull llama3.2:1b
docker compose exec ollama ollama pull bge-m3
docker compose exec vexa cat /data/credenciales_admin_inicial.txt   # contraseña inicial del admin
docker compose exec vexa rm /data/credenciales_admin_inicial.txt    # bórrala después de anotarla
```

Abre `http://<IP 100.x>:5000` desde un dispositivo de tu tailnet (el PC anfitrión también, si está en Tailscale). En los PCs de abogados: `configurar-cliente.ps1 -Url http://<IP 100.x>:5000`.

**Clave de Tailscale (opcional):** en lugar del enlace interactivo puedes ejecutar `$env:TS_AUTHKEY='tskey-…'; docker compose up -d` **solo la primera vez**. El estado queda en el volumen `tailscale_estado`; no guardes la clave en archivos.

## Operación

| Tarea | Comando |
|---|---|
| Estado | `docker compose ps` (VEXA y Tailscale tienen healthcheck) |
| Logs | `docker compose logs -f vexa` |
| Actualizar código | `docker compose up -d --build vexa` (las migraciones respaldan la base antes) |
| Detener | `docker compose down` (los volúmenes se conservan; **nunca** uses `down -v`) |

## Respaldos

`backup_vexa.py` es para Windows (DPAPI). En Docker, respalda el volumen con VEXA detenido:

```powershell
docker compose stop vexa
docker run --rm -v vexa_vexa_datos:/data -v ${PWD}\respaldos:/respaldo alpine tar czf /respaldo/vexa-datos.tgz -C /data .
docker compose start vexa
```

El archivo contiene la base, los documentos **y la clave**: guárdalo en un disco externo cifrado, nunca en OneDrive/Drive. Restaurar: `tar xzf` sobre un volumen vacío con VEXA detenido.

## Limitaciones verificadas

El backend se probó en Windows; la imagen no se construyó en este equipo (Docker no estaba instalado). Prueba `docker compose up --build` y revisa `docker compose logs vexa` la primera vez.
