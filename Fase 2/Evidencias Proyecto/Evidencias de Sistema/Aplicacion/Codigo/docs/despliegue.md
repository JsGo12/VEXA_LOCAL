# Despliegue en la firma: un servidor y PCs de abogados

```text
PC SERVIDOR (administrador)                       PCs DE ABOGADOS
├─ Waitress  127.0.0.1:5000 + 100.x.y.z:5000       ├─ Tailscale
├─ Ollama + modelos (toda la IA corre aquí)        └─ Navegador o app VEXA en modo cliente
├─ SQLite + documentos cifrados                       → http://100.x.y.z:5000
└─ Tailscale
```

Solo el servidor guarda y procesa documentos. Los PCs de abogados **no necesitan** Python ni Ollama, y no guardan casos.

> No instales la app de escritorio en modo local en los PCs de abogados: crearía una base vacía en ese equipo. Usa el navegador o el modo cliente (paso 4).

## 1. PC servidor

Una sola vez, desde `Codigo\` en PowerShell, con la cuenta de Windows del administrador:

```powershell
# Software: Python 3, Ollama y Tailscale instalados; Tailscale con la sesión iniciada.
ollama pull llama3.2:1b          # con 16 GB de RAM o más: ollama pull llama3.2
ollama pull bge-m3
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe backend\scripts\init_env.py
```

Edita `Codigo\.env`:

```dotenv
VEXA_ENV=production
TAILSCALE_ENABLED=true
TAILSCALE_BIND_ADDRESS=          # vacío = detecta la IP con `tailscale ip -4`
VEXA_THREADS=8
```

Comprueba la configuración y deja el servidor automatizado:

```powershell
.\.venv\Scripts\python.exe backend\run.py --check                       # debe mostrar 127.0.0.1 y 100.x
.\scripts\servidor\registrar-inicio.ps1 -SinSuspension                   # tarea "VEXA Servidor" al iniciar sesión
Start-ScheduledTask -TaskName 'VEXA Servidor'
# PowerShell como administrador:
.\scripts\servidor\firewall-tailscale.ps1                                # puerto 5000 solo desde Tailscale
# Respaldo semanal a un disco que no esté en OneDrive:
.\scripts\servidor\respaldo.ps1 -Programar -Destino E:\RespaldosVEXA
```

- La tarea se ejecuta con la cuenta del administrador. Es obligatorio: la clave de cifrado está protegida con DPAPI para esa cuenta. El servidor funciona mientras esa sesión de Windows esté iniciada; bloquear la pantalla no lo detiene.
- Registros: `%USERPROFILE%\.vexa_local\logs\servidor-AAAAMMDD.log`.
- Para usar la app de escritorio en el propio servidor, Electron se conecta al servidor que ya está activo.

## 2. Red privada (consola de Tailscale)

1. *Settings → Device management → Device approval*: actívalo y aprueba solo los PCs de la firma.
2. Ponle la etiqueta `tag:vexa-server` al servidor y desactiva la caducidad de su clave (*Disable key expiry*).
3. En *Access controls*, permite que solo el grupo de abogados llegue al puerto 5000 del servidor (ejemplo de ACL en [tailscale.md](tailscale.md)).
4. Opcional: usa el nombre MagicDNS (`http://servidor-vexa:5000`) y defínelo en `TAILSCALE_HOST`.

## 3. Cuentas y casos (panel web del administrador)

1. Entra con `admin` y la contraseña de `credenciales_admin_inicial.txt`. VEXA pedirá cambiarla; después borra ese archivo.
2. **Administración → Crear cuenta** (rol *Abogado/a*) para cada abogado, con una contraseña temporal. Cada persona deberá cambiarla en su primer inicio de sesión.
3. Crea equipos si lo necesitas. Después, **Crear y asignar caso** con sus documentos.
4. Para agregar documentos a un caso existente: ábrelo y usa **Agregar documentos** (solo administrador o abogado jefe).
5. Si un abogado olvida su contraseña: **Administración → Usuarios → Contraseña temporal**.

## 4. Cada PC de abogado

1. Instala Tailscale e inicia sesión con la cuenta de la firma. El administrador aprueba el equipo.
2. Abre `http://100.x.y.z:5000` en el navegador y guárdalo como favorito. También puedes crear un acceso directo:
   ```powershell
   .\configurar-cliente.ps1 -Url http://100.x.y.z:5000 -AccesoDirecto
   ```
   El script está en `Codigo\desktop\electron\`. Cópialo al PC del abogado o ejecútalo desde una copia del repositorio.
3. Opcional, con la app de escritorio VEXA instalada: el mismo comando hace que la app abra el servidor de la firma en lugar de iniciar uno local. Para volver al modo local: `.\configurar-cliente.ps1 -Quitar`.
4. Inicia sesión, cambia la contraseña temporal y comprueba que ves solo tus casos.

## 5. Uso diario

| Persona | Qué hace |
|---|---|
| Abogado/a | **Mis casos** → abre un caso → chat con la IA, resumen automático, descargas. En **Avance del caso** registra estado, porcentaje y notas. |
| Administrador | **Seguimiento**: casos por estado, vencidos, vencen en 7 días, casos sin actualizaciones y última actividad. Abre cada caso para leer las notas de avance. **Auditoría**: accesos y denegaciones. |

## 6. Pruebas antes de usarlo con casos

- [ ] Desde un PC de abogado: solo ve sus casos, y abrir otro caso devuelve "No tienes acceso".
- [ ] El chat responde y muestra fuentes, y el resumen aparece tras la indexación.
- [ ] El abogado registra un avance y el administrador lo ve en **Seguimiento**.
- [ ] Desde un equipo **sin** Tailscale, `http://<IP de la red local del servidor>:5000` no responde.
- [ ] Dos abogados consultan a la vez. Si va lento, usa un modelo más liviano o sube `VEXA_THREADS`.
- [ ] En **Auditoría** aparecen los inicios de sesión y los accesos denegados.
- [ ] `respaldo.ps1 -Ejecutar -Destino …` y una restauración en una carpeta de prueba (`backup_vexa.py restore … --target C:\prueba`) funcionan.
