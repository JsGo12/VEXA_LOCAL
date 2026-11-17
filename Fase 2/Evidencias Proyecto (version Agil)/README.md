# VEXA Local

**Nombre del proyecto:** Vexa Local — asistente de IA local para consultar expedientes jurídicos con fuentes citadas

**Descripción:** Aplicación de escritorio para Windows que organiza expedientes jurídicos y permite consultarlos con IA generativa que se ejecuta en el propio equipo (Ollama), mediante una arquitectura RAG. Proyecto de Título APT122 (Capstone) — Duoc UC, Ingeniería Informática, sede Alameda.

> Prototipo académico: usa documentos ficticios. No cargues expedientes reales ni datos personales.

---

## Tabla de contenidos

- [Descripción](#descripción)
- [Tecnologías utilizadas](#tecnologías-utilizadas)
- [Instrucciones para ejecutar el proyecto](#instrucciones-para-ejecutar-el-proyecto)
- [Integrantes del equipo](#integrantes-del-equipo)
- [Metodología de trabajo](#metodología-de-trabajo)
- [Arquitectura de la solución](#arquitectura-de-la-solución)
- [Estructura del repositorio](#estructura-del-repositorio)
- [Documentación del proyecto (Fase 2)](#documentación-del-proyecto-fase-2)
- [Estado y limitaciones](#estado-y-limitaciones)

## Descripción

Los estudios jurídicos acumulan contratos, fichas y normativas que sus equipos consultan a diario. Buscar un dato abriendo archivo por archivo es lento, y usar una IA en la nube obliga a enviar documentos confidenciales fuera de la organización, lo que choca con el secreto profesional y con la Ley 19.628. Vexa Local ofrece una alternativa que procesa todo en el propio equipo.

### Usuarios y roles

| Rol | Qué hace |
| --- | --- |
| Administrador | Crea cuentas, equipos y casos, administra permisos y alcance, ve el seguimiento de los casos y la auditoría |
| Abogado/a jefe | Ve los casos de los abogados a su cargo (los define el administrador), registra el avance y cierra casos con un motivo, y usa el asistente transversal sobre los expedientes que tiene autorizados |
| Abogado/a | Ve solo los casos de su alcance, consulta el chat del caso con fuentes citadas, agrega notas y escribe mensajes al equipo del caso |

El sistema tiene 17 permisos asignables y un alcance de datos por caso (asignado, por equipo o concedido), con denegación por defecto.

### Qué incluye

- Cuentas con contraseña cifrada (hash), contraseña temporal obligatoria de cambiar y cierre de sesiones al cambiar rol o contraseña.
- Equipos, casos con fecha límite, asignación a una persona o a un equipo y carga de documentos (PDF, DOCX, XLSX, PPTX, TXT y CSV; OCR opcional).
- Chat por caso con respuestas progresivas y fuentes (documento y página), y asistente transversal para el abogado/a jefe.
- Seguimiento de casos (estado, avance y cierre con motivo, notas cifradas y semáforo de plazo), mensajes del equipo cifrados y notificaciones con recordatorios de plazo.
- Auditoría en lenguaje claro con retención configurable (14 días por defecto) y exportaciones a Excel; perfil de usuario y descarga del expediente en ZIP.
- Respaldo automático cada 24 horas (se guardan 7) y clave de recuperación opcional para restaurar en otro equipo.
- Recuperación híbrida (BM25 más búsqueda semántica opcional con bge-m3) y cifrado en reposo de documentos, fragmentos, vectores, chats y resúmenes.
- Acceso remoto privado opcional con Tailscale.

### Fuera del alcance

- Sincronización entre servidores y un servicio central en la nube.
- Autenticación de dos factores y cifrado integral de los metadatos.
- Uso con expedientes reales.

## Tecnologías utilizadas

| Categoría | Tecnología |
| --- | --- |
| Lenguajes | Python (backend) y JavaScript (interfaz) |
| Backend | Flask servido con Waitress, SQLite con migraciones versionadas |
| Escritorio | Electron, empaquetado con PyInstaller y electron-builder (NSIS) |
| IA local | Ollama (llama3.1:8b, llama3.2 o llama3.2:1b según el equipo) y embeddings bge-m3 opcionales |
| Recuperación | BM25 (rank-bm25) y búsqueda semántica fusionadas con RRF |
| Seguridad | Cifrado Fernet con clave protegida por DPAPI de Windows |
| Acceso remoto | Tailscale (opcional) |
| Contenedores | Docker y docker-compose (alternativa de servidor, sin probar) |
| Pruebas | pytest (174 funciones de prueba en 21 archivos) |

## Instrucciones para ejecutar el proyecto

Requisitos: Windows 10/11 de 64 bits, Python 3, Node.js LTS y [Ollama](https://ollama.com/download/windows). La configuración inicial necesita Internet; las consultas no.

```powershell
# 1. Modelos locales (bge-m3 es opcional)
ollama pull llama3.2:1b
ollama pull bge-m3

# 2. Desde la carpeta Codigo: entorno y dependencias
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 3. Configuración y validación
.\.venv\Scripts\python.exe backend\scripts\init_env.py
.\.venv\Scripts\python.exe backend\run.py --check

# 4a. Aplicación de escritorio
Set-Location .\desktop\electron
.\setup-dev.ps1
corepack pnpm start

# 4b. O solo el servidor (navegador o Tailscale)
.\.venv\Scripts\python.exe backend\run.py   # http://127.0.0.1:5000
```

En el primer inicio se crea el usuario `admin` con una contraseña aleatoria, escrita en `%USERPROFILE%\.vexa_local\credenciales_admin_inicial.txt`. El sistema exige cambiarla al primer ingreso. La guía completa está en [`Codigo/README.md`](Codigo/README.md) y en la carpeta [`Codigo/docs/`](Codigo/docs/).

### Pruebas

```powershell
.\.venv\Scripts\python.exe -m pytest -q backend\tests
```

## Integrantes del equipo

| Integrante | Rol |
| --- | --- |
| Héctor Schulz | Jefe de proyecto y desarrollador full-stack |
| Ignacio López | Desarrollador backend y especialista en IA/RAG |
| Josué García | Desarrollador frontend y diseñador UX/UI |

## Metodología de trabajo

CRISP-DM con enfoque iterativo-incremental, sprints semanales de inspiración Scrum (S1 comenzó el 24/08/2026), GitFlow simplificado sobre GitHub y un tablero Kanban con tres estados (pendiente, en curso y terminada). El detalle y la justificación están en el documento *Metodología declarada y justificada*.

## Arquitectura de la solución

```text
Electron (o navegador)  →  Flask + Waitress (127.0.0.1, opcional IP Tailscale)
                              ├─ permisos y alcance  ─ auditoría
                              ├─ SQLite (23 tablas, cifrado por columna)
                              ├─ documentos cifrados en disco
                              └─ RAG: lectura de formatos → fragmentos → BM25 + vectores → Ollama (solo loopback)
```

| Decisión | Elección | Motivo |
| --- | --- | --- |
| Interfaz | Electron + interfaz web | Instalador de Windows simple para usuarios no técnicos |
| Backend | Flask con Waitress | Suficiente para un servidor local y fácil de empaquetar |
| Base de datos | SQLite | Sin instalación; encaja con un servidor por organización |
| Recuperación | BM25 + semántica opcional | Degrada bien si falta el modelo de embeddings |
| IA | Ollama local | Evita enviar expedientes a servicios externos |
| Acceso remoto | Tailscale opcional | Red privada cifrada, sin publicar puertos ni usar `0.0.0.0` |

El detalle está en el documento *Arquitectura* y en [`Codigo/docs/arquitectura.md`](Codigo/docs/arquitectura.md).

## Estructura del repositorio

```text
VEXA_LOCAL/
├── Codigo/        Aplicación (backend, frontend, Electron, scripts y docs)
├── Fase 1/        Evidencias de la Fase 1 (definición del proyecto)
├── Fase 2/        Evidencias de la Fase 2 (desarrollo)
│   ├── Evidencias Grupales/
│   ├── Evidencias Individuales/
│   └── Evidencias Proyecto (version Agil)/
├── historico/     Versión anterior del código (solo referencia)
└── README.md
```

## Documentación del proyecto (Fase 2)

Los documentos están en `Fase 2/Evidencias Proyecto (version Agil)/`, salvo que se indique otra ruta.

| Documento | Contenido |
| --- | --- |
| Documento de inicio de proyecto (`Evidencias Grupales/`) | Planificación inicial y fundamentación |
| Metodología declarada y justificada | CRISP-DM, sprints, GitFlow y Kanban |
| Product Vision, Product Backlog, Sprint Backlog, Definition of Done | Planificación ágil y criterios de terminado |
| Retrospectiva | Lecciones aprendidas |
| SRS y Requisitos no funcionales | Requisitos funcionales (70) y no funcionales (24) |
| Arquitectura, Diagramas UML y Modelo de datos (`esquema_vexa.sql`) | Diseño de la solución |
| Guía de instalación y configuración (Manual técnico) | Instalación, configuración, operación y acceso remoto |
| Evidencias de documentación | Manual de usuario y documento de arquitectura |
| Informe de privacidad y protocolo de captura | Verificación de que el sistema opera de forma local |
| Pruebas | Plan e informe de pruebas |
| Innovación | Aporte de valor y límites de la solución |

## Estado y limitaciones

- Las 174 pruebas automatizadas todavía no se han ejecutado en Windows sobre el código final.
- La captura de tráfico de red (con y sin Tailscale) y la evaluación de precisión y tiempos están planificadas para S15–S16.
- El instalador no se ha probado en un Windows limpio, y la imagen de Docker no se ha construido ni probado.
- Algunos metadatos (nombres de usuario, títulos de caso, nombres de archivo y auditoría) no se cifran.
- Con Tailscale hay comunicación con su servidor de coordinación externo; el modo remoto no equivale a cero conexiones externas.
