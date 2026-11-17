# Respaldos y restauración

## Respaldo automático (lo hace el servidor)

Mientras el servidor está encendido, VEXA crea un respaldo cifrado **cada 24 horas** (el primero, un minuto después de arrancar) y conserva los **últimos 7**, sin detenerse. El estado se ve en **Administración → Respaldos**, donde también hay un botón «Crear respaldo ahora». Solo el administrador ve esa pestaña.

| Variable | Predeterminado | Qué hace |
|---|---|---|
| `VEXA_BACKUP_DIR` | `%USERPROFILE%\VEXA_respaldos` | Carpeta de los respaldos. **Ponla en un disco externo** (`E:\RespaldosVEXA`). Debe estar fuera de la carpeta de datos. |
| `VEXA_BACKUP_HOURS` | `24` | Cada cuántas horas. `0` desactiva el respaldo automático. |
| `VEXA_BACKUP_KEEP` | `7` | Cuántos respaldos conservar; los más antiguos se borran. |

La pestaña avisa si la carpeta está en el **mismo disco** que los datos (protege ante borrados o errores, pero no si el disco falla) o si parece **sincronizada con la nube** (los respaldos contienen todos los expedientes: no los pongas en OneDrive).

La base se copia con la API de respaldo de SQLite (consistente aunque haya escrituras); los documentos ya están cifrados en disco. Las copias previas a migraciones (`backups\` dentro de la carpeta de datos) no se incluyen.

## Clave de recuperación (hazlo una vez)

`vault.key` está protegida con DPAPI, es decir, atada a la cuenta de Windows del servidor. Si el PC se daña o se reinstala Windows, ni los datos ni los respaldos se pueden abrir sin una copia de la clave. Créala **en el PC servidor**, desde `Codigo/`:

```powershell
.\.venv\Scripts\python.exe backend\scripts\clave_recuperacion.py E:\vexa-clave-recuperacion.vexakey
```

- Pide una contraseña (mínimo 12 caracteres) que **no se guarda en ningún lado**: anótala en un lugar distinto al del archivo.
- El archivo es la clave cifrada con esa contraseña (scrypt + Fernet). Guárdalo en una USB o disco externo, nunca en la nube.
- Solo se crea desde la línea de comandos del servidor, nunca desde la web. En la carpeta de datos queda `recuperacion.json` con la fecha y una huella (no la clave), para que la pestaña Respaldos muestre «✓ Creada» y avise si deja de coincidir.

## Restaurar

Detén VEXA (servidor y Electron) y, desde `Codigo/`:

```powershell
# En el mismo servidor y la misma cuenta de Windows
.\.venv\Scripts\python.exe backend\scripts\backup_vexa.py restore "E:\RespaldosVEXA\vexa-20261114-030000.vexabackup" --replace

# En otro PC u otra cuenta (PC dañado, Windows reinstalado)
.\.venv\Scripts\python.exe backend\scripts\backup_vexa.py restore "E:\RespaldosVEXA\vexa-...vexabackup" --clave-recuperacion E:\vexa-clave-recuperacion.vexakey
```

El destino (por defecto `VEXA_DATA_DIR`, o `--target`) debe estar vacío. Con `--replace` la carpeta actual se conserva al lado con el sufijo `.before-restore-<fecha>`; verifica que VEXA abre bien antes de borrarla. Con la clave de recuperación, la clave restaurada se vuelve a proteger con DPAPI para la cuenta actual; los datos cifrados no cambian.

## Formato

Los respaldos nuevos usan `VEXABAK2`: la clave aleatoria del archivo va envuelta con DPAPI (restauración normal) y con la clave del vault (restauración con la clave de recuperación). Los respaldos anteriores (`VEXABAK1`, solo DPAPI) se siguen restaurando en la misma cuenta.

## Respaldo manual por línea de comandos

```powershell
.\.venv\Scripts\python.exe backend\scripts\backup_vexa.py create "E:\RespaldosVEXA\vexa-manual.vexabackup"
```

`scripts\servidor\respaldo.ps1` (detiene el servidor, respalda y lo reinicia) sigue disponible, pero ya no es necesario: el servidor respalda solo.

## Respaldos automáticos de migración

Antes de aplicar migraciones a una base con datos, VEXA guarda `backups\vexa_web-antes-de-migrar-v<N>-<fecha>.db` dentro de la carpeta de datos (ver [migraciones.md](migraciones.md)). Puedes borrarlas cuando confirmes que la nueva versión funciona.
