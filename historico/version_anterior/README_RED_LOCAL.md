# VEXA en red local: guía de demostración

Esta versión agrega un flujo web con cuentas separadas para administrador y abogados. `main.py` conserva la interfaz de escritorio previa; la versión con acceso por navegador se inicia con `web_app.py`.

## Iniciar en el computador que hará de servidor

Desde una terminal de VS Code:

```powershell
cd "C:\Users\josue\Documents\ChatGPT\CAPSTONE - VEXA\01_VEXA_LOCAL-main"
pip install -r requirements.txt
python web_app.py
```

La primera visita a `http://127.0.0.1:5000` mostrará el formulario para crear la cuenta administradora. Los datos se guardan en `%USERPROFILE%\.vexa_local\vexa_web.db`; los documentos se guardan localmente en `%USERPROFILE%\.vexa_local\case_documents`.

Ollama debe estar iniciado en ese computador y tener disponible el modelo `llama3.2`, que es el primer modelo configurado en `rag_core.py`.

## Probar las dos vistas

1. Inicia sesión como administrador.
2. Crea una cuenta para uno o más abogados.
3. Crea un equipo y selecciona sus integrantes, si el caso se asignará al grupo.
4. Crea un caso, escribe un resumen breve, indica la fecha límite, selecciona a la persona o equipo y adjunta documentos PDF o DOCX ficticios.
5. Cierra la sesión del administrador e inicia con la cuenta del abogado.
6. En “Mis casos”, abre el caso para descargar sus documentos o consultar el chat.

## Probar desde otro equipo de la misma red

El servidor escucha en el puerto `5000` en las interfaces de red locales. En el computador servidor, ejecuta `ipconfig` y localiza la dirección IPv4 de su red. Desde el otro equipo, abre `http://DIRECCION-IP-DEL-SERVIDOR:5000` en el navegador. Si Windows Firewall pregunta, permite el acceso solo en la red privada de demostración.

## Alcance de este prototipo

- El servidor valida en el backend que cada abogado pertenezca al equipo o sea la persona asignada antes de mostrar el caso, descargar sus archivos o consultar el chat.
- La indexación RAG se conserva en memoria por caso mientras corre el servidor; al reiniciar se reconstruirá cuando se vuelva a consultar.
- El chat usa BM25. En expedientes con muy pocos fragmentos, el ranking usa coincidencia léxica como respaldo para no descartar contexto por scores cero o negativos. Si la consulta no comparte términos con el documento, prueba con un nombre, una fecha, un monto o una frase textual.
- La vista del abogado muestra el resumen ingresado al crear el caso y una vista previa del primer documento para casos guardados con una versión anterior.
- En el caso, el indicador del chat distingue si Ollama responde, si falta el modelo `llama3.2` o si el servidor de Ollama está apagado.
- Esta versión está preparada para una presentación académica con datos sintéticos. Usa el servidor de desarrollo de Flask y HTTP sin cifrado TLS; no la expongas a Internet ni la uses con expedientes reales. Una instalación para un estudio requiere despliegue endurecido, HTTPS, copias de seguridad, controles de operación y revisión de seguridad.
