# Backend local para VEXA Desktop

Electron inicia el backend Flask en una dirección local (`127.0.0.1`) y abre la interfaz en una ventana nativa. Para desarrollo, la app Electron usa el Python disponible en el equipo. Para crear el instalador de Windows, `build.ps1` empaqueta `web_app.py`, sus plantillas, recursos estáticos y dependencias con PyInstaller.

Ollama y el modelo `llama3.2:1b` se instalan por separado en el equipo. La aplicación necesita que Ollama esté iniciado para responder consultas con IA.
