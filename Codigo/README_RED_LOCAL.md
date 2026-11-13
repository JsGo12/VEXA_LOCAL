# VEXA Local: alcance de red y comprobación de tráfico

## Alcance

- **Modo local (predeterminado):** el backend escucha únicamente en `127.0.0.1`. `VEXA_HOST` solo admite loopback; un valor como `0.0.0.0` o una IP de la red local detiene el arranque con un error de configuración. Electron usa un puerto local aleatorio.
- **Modo Tailscale (opcional):** con `TAILSCALE_ENABLED=true`, el servidor Waitress independiente (`backend\run.py`) escucha además en la IP 100.x de Tailscale del equipo. No se usa `0.0.0.0`, Funnel ni port forwarding. Ver [docs/tailscale.md](docs/tailscale.md).
- En ambos modos, cada petición cuyo origen no sea loopback (o Tailscale, si está activo) recibe 403.
- Ollama se consulta en `127.0.0.1:11434`; VEXA rechaza un `OLLAMA_HOST` externo.

## Comprobar el listener

```powershell
Get-NetTCPConnection -State Listen -LocalPort 5000 |
  Select-Object LocalAddress, LocalPort, OwningProcess
```

En modo local, `LocalAddress` debe ser solo `127.0.0.1`; con Tailscale, `127.0.0.1` y la IP `100.x`. Electron usa un puerto dinámico: consulta `%USERPROFILE%\.vexa_local\server.json` o busca el proceso `python`/`VexaBackend` en el Monitor de recursos (`resmon.exe` → Red).

## Protocolo breve para observar tráfico

1. Usa documentos ficticios y cierra navegadores, sincronizadores y otras aplicaciones que generen tráfico de fondo. Anota la hora de inicio y el estado de Ollama.
2. Abre el Monitor de recursos (`resmon.exe`) → **Red**. En **Procesos con actividad de red**, localiza `python`, `VexaBackend` y el proceso de Ollama. Revisa las direcciones remotas mientras abres un caso y haces una consulta.
3. Para una captura más detallada, usa Wireshark en la interfaz activa y, para localhost, el adaptador de loopback de Npcap. El tráfico del backend a Ollama debe quedarse en loopback; no atribuyas al proyecto conexiones de otros procesos.
4. Con Tailscale activo verás además tráfico de `tailscaled` hacia la coordinación de Tailscale y, a veces, relays DERP: es el plano de control/transporte cifrado de la VPN, no contenido de VEXA.
5. Conserva la captura solo si es necesaria: puede contener nombres de host y metadatos. Los informes del evaluador RAG pueden contener respuestas documentales: guárdalos bajo `%USERPROFILE%\.vexa_local`.

La app no necesita un servidor externo para consultar documentos. La instalación sí requiere Internet para dependencias, Ollama y modelos. Esta comprobación observa una ejecución concreta; no sustituye una auditoría de cada proceso del sistema.
