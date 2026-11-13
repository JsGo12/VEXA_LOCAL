# Seguridad

Resumen de controles y de sus límites. Cada control tiene pruebas en `backend/tests`.

## Red

- Waitress escucha en `127.0.0.1` y, solo con `TAILSCALE_ENABLED=true`, también en la IP 100.x de Tailscale. `0.0.0.0`, `::` y direcciones LAN se rechazan en la configuración.
- `RemoteAddressFilter` (WSGI) responde 403 a cualquier origen fuera de loopback/Tailscale.
- `TRUSTED_HOSTS` de Flask limita las cabeceras `Host` aceptadas (mitiga DNS rebinding).
- Una sola instancia de servidor por carpeta de datos (`vexa_server.lock`).
- Sin Funnel, túneles públicos, port forwarding ni APIs externas. `OLLAMA_HOST` debe ser loopback.

## Autenticación y sesiones

- Contraseñas con hash de Werkzeug (scrypt/pbkdf2). Mínimo 10 caracteres (12 para el admin inicial).
- Bloqueo de 5 minutos tras 5 intentos fallidos por usuario (con escritura atómica).
- `session.clear()` al iniciar sesión (sin fijación de sesión); cookie `HttpOnly`, `SameSite=Lax`, `Secure` configurable, vigencia de 8 horas.
- Cada petición recarga al usuario: una cuenta desactivada pierde la sesión de inmediato.
- No existe registro público: `/setup` solo redirige.

## CSRF, XSS y cabeceras

- Token CSRF por sesión, obligatorio en todo `POST` (formulario o cabecera `X-CSRF-Token`).
- Jinja escapa la salida; el JS inserta texto con `textContent`, nunca `innerHTML` con datos.
- `Content-Security-Policy` sin scripts ni estilos en línea, `frame-ancestors 'none'`, `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store` para páginas con sesión.

## Autorización

Denegación por defecto, comprobada en el backend en cada ruta sensible, antes de indexar o recuperar documentos (RAG), antes de descargar y en el asistente. Ver [permisos.md](permisos.md).

## Datos y archivos

- Cifrado en reposo (Fernet/AES-128-CBC + HMAC) de documentos, archivos procesados de la carpeta vigilada, historial de chat y del asistente, fragmentos, embeddings y resúmenes. La clave (`vault.key`) se protege con DPAPI en Windows; si DPAPI falla al crear una clave nueva, VEXA se detiene (no cae a texto plano).
- Un documento corrupto o con otra clave falla de forma cerrada: el usuario ve un error genérico, sin trazas.
- Subidas: extensiones permitidas, nombre saneado (`secure_filename`), 30 MB por archivo, nombre en disco aleatorio (UUID). Los archivos se sirven solo por `/documents/<id>` tras autorizar; las carpetas de datos nunca son estáticas.
- SQL siempre parametrizado; los únicos fragmentos dinámicos son nombres de columna fijos del código.
- Metadatos sin cifrar en SQLite: nombres de usuario, títulos de caso, nombres de archivo y auditoría.

## Auditoría y logs

`audit_log` registra inicios/cierres de sesión, cuentas, roles, equipos, asignaciones, permisos, aperturas de casos, descargas, uso del asistente y denegaciones (usuario, acción, recurso, fecha UTC, resultado, motivo, IP). Nunca guarda contraseñas, tokens, preguntas ni contenido documental. Los logs del servidor no imprimen secretos ni el `.env`.

## Errores

Los errores 400/403/404/413/500 se muestran con una página o JSON genérico. Las trazas solo van al log del servidor.

## IA

- El contenido documental se trata como dato no confiable: los prompts indican ignorar instrucciones incrustadas en documentos.
- El modelo solo recibe fragmentos ya autorizados; no tiene acceso a archivos ni a la base.

## Riesgos conocidos y pendientes

- Sin TLS propio: dentro de la tailnet el tráfico va cifrado por WireGuard; para HTTPS usar `tailscale serve` (ver [tailscale.md](tailscale.md)).
- Los administradores del sistema operativo del servidor pueden leer la memoria del proceso; DPAPI protege frente a otras cuentas, no frente al propio usuario de Windows.
- No hay límite de tasa por IP ni MFA.
- La ocultación de respuestas antiguas del chat por expediente se basa en el nombre del documento citado y puede ocultar de más si hay nombres repetidos.
