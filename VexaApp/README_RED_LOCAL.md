# VEXA Local: alcance y comprobación de red

Esta guía reemplaza las instrucciones antiguas para abrir VEXA desde otro computador. La versión actual es de un solo equipo: el backend Flask escucha únicamente en `127.0.0.1`. La variable `VEXA_HOST` se ignora al ejecutar `web_app.py`; no la cambies para exponer VEXA a la red. Electron elige un puerto local disponible y abre esa dirección dentro de su ventana.

## Comprobar el listener

En el modo web de desarrollo, el puerto predeterminado es `5000`. En PowerShell:

```powershell
Get-NetTCPConnection -State Listen |
  Where-Object LocalPort -eq 5000 |
  Select-Object LocalAddress, LocalPort, OwningProcess
```

`LocalAddress` debe ser `127.0.0.1`. Electron usa un puerto dinámico; busca las conexiones del proceso Python o `VexaBackend` en el Monitor de recursos (`resmon.exe` → Red). Las conexiones de la app a Ollama deben apuntar a `localhost:11434`.

## Protocolo breve para observar tráfico

1. Usa documentos ficticios y cierra navegadores, sincronizadores y otras aplicaciones que generen tráfico de fondo. Anota la hora de inicio y el estado de Ollama.
2. Abre el Monitor de recursos (`resmon.exe`) → **Red**. En **Procesos con actividad de red**, localiza `python`, `VexaBackend` y el proceso de Ollama. Revisa las direcciones remotas asociadas mientras abres un caso y haces una consulta.
3. Para una captura de paquetes más detallada, usa Wireshark en la interfaz Wi-Fi/Ethernet activa y, si necesitas inspeccionar localhost, en su adaptador de loopback Npcap. Compara una captura en reposo con otra durante la consulta. El tráfico del backend a Ollama debe quedarse en loopback; no atribuyas automáticamente al proyecto conexiones de otros procesos del sistema.
4. Conserva la captura solo si es necesaria para la revisión; puede contener nombres de host y metadatos de red. El evaluador local de RAG puede generar actividad en Ollama, pero sus informes pueden contener respuestas documentales: guárdalos bajo `%USERPROFILE%\.vexa_local`.

La app no necesita un servidor externo para consultar documentos. La configuración inicial sí requiere Internet para instalar dependencias y descargar Ollama/modelos; esas descargas las inicia el usuario fuera de una consulta RAG. Esta comprobación observa el tráfico de una ejecución concreta, no sustituye una auditoría de cada proceso del sistema ni demuestra por sí sola la ausencia de cualquier conexión futura.

## Inicio desde el código fuente

Desde la carpeta `VexaApp`, instala primero los requisitos de Python y sigue los pasos de Electron descritos en [README.md](README.md):

```powershell
python -m pip install -r requirements.txt
Set-Location .\desktop\electron
.\setup-dev.ps1
```
