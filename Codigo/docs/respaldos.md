# Respaldos y restauración

## Respaldo completo cifrado

Cierra VEXA (Electron y cualquier `run.py`) y, desde `Codigo/`:

```powershell
.\.venv\Scripts\python.exe backend\scripts\backup_vexa.py create "D:\Respaldos\vexa.vexabackup"
```

Incluye la base SQLite (copia consistente), la clave del vault protegida por DPAPI y los archivos de `VEXA_DATA_DIR`. El archivo completo se cifra y **solo puede restaurarse con la misma cuenta de Windows**. Si `VEXA_WATCH_DIR` apunta fuera de la carpeta de datos, el comando se detiene para no producir un respaldo incompleto.

Guarda el respaldo fuera de OneDrive o de carpetas sincronizadas y nunca lo subas a GitHub: contiene metadatos y datos de casos.

## Restaurar

```powershell
.\.venv\Scripts\python.exe backend\scripts\backup_vexa.py restore "D:\Respaldos\vexa.vexabackup"
```

El destino (por defecto `VEXA_DATA_DIR`, o `--target`) debe estar vacío. Para reemplazar datos existentes añade `--replace`: la carpeta actual se conserva al lado con el sufijo `.before-restore-<fecha>`. Verifica que VEXA abre bien antes de borrar esa copia.

## Respaldos automáticos de migración

Antes de aplicar migraciones a una base con datos, VEXA guarda `backups\vexa_web-antes-de-migrar-v<N>-<fecha>.db` dentro de la carpeta de datos (ver [migraciones.md](migraciones.md)). Son copias de la base (los documentos siguen cifrados en `case_documents`). Puedes borrarlas cuando confirmes que la nueva versión funciona.

## Cambiar de equipo o de cuenta de Windows

La clave del vault está ligada a la cuenta de Windows (DPAPI). Copiar la base y los archivos cifrados a otra cuenta **no basta**: se necesita una exportación con descifrado y nuevo cifrado, que esta versión no automatiza.
