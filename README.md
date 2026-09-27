# Nombre del Proyecto 
  Vexa Local

## Descripción del Proyecto

  ### Propósito del Sistema
  El proyecto es una aplicación de escritorio con interfaz web embebida orientada a la gestión, búsqueda e interacción inteligente con documentos locales mediante procesamiento de lenguaje natural y algoritmos de recuperación de información.

  ### Público Objetivo
  Está diseñado para equipos de trabajo, administradores de sistemas y usuarios finales dentro de organizaciones que requieren un control riguroso sobre la asignación de archivos y una consulta rápida de documentación sin depender de servicios en la nube externos.

  ### Problema que Resuelve
  Elimina las altas latencias asociadas a la lectura e indexación recurrente de archivos pesados y resuelve la falta de control en la gestión documental mediante un mecanismo de precarga en memoria y un sistema de delegación temporal de archivos.

## Tecnologías Utilizadas

* **Lenguaje de Programación:** Python 3.10+
* **Interfaz de Usuario:** PyWebView, HTML5, CSS3, JavaScript
* **Procesamiento de Lenguaje Natural e IA:** Ollama (Modelo LLaMA 3.2:3b)
* **Algoritmos de Búsqueda:** Rank-BM25
* **Procesamiento de Imágenes y Documentos:** Pillow
* **Empaquetado:** PyInstaller

## Instrucciones para Ejecutar el Proyecto Localmente

### Requisitos Previos y Dependencias

Asegúrese de contar con Python 3.10 o superior y la herramienta Ollama instaladas en el sistema.

Las librerías requeridas para el proyecto se detallan a continuación (pueden almacenarse en un archivo `requirements.txt`):

```text
pywebview
rank-bm25
ollama
pyinstaller
pillow
```

### Pasos de Instalación y Ejecución

Instalar dependencias de Python:

Bash
pip install pywebview rank-bm25 ollama pyinstaller pillow
(O utilizando el archivo de dependencias: pip install -r requirements.txt)

Iniciar el servicio y descargar el modelo en Ollama:
Inicie el servidor local de Ollama:

Bash
ollama serve
En una segunda terminal, descargue el modelo de lenguaje requerido:

Bash
ollama pull llama3.2:3b
Ejecutar la aplicación en modo desarrollo:

Bash
python main_2.py
Empaquetar la aplicación para distribución (Ejecutable):
Para generar el archivo ejecutable autocontenido junto con la interfaz web:

Bash
pyinstaller --noconsole --onefile --add-data "interface_2.html;." main_2.py



## Integrantes del Equipo y sus Roles

1. Hector Schulz: Jefe de Proyecto & Desarrollador Full-Stack (Líder del Proyecto)

Área de trabajo principal: main.py, gestión del repositorio, configuración del sistema.

Responsabilidades:

Gestión: Planificar los tiempos de entrega, coordinar las tareas del equipo y asegurar que la aplicación cumpla con los requisitos.

Integración: Crear la ventana nativa de la app con pywebview y unir el trabajo del Frontend con el Backend.

Seguridad y Core: Implementar la lógica de autenticación (PIN, cifrado SHA-256) y el manejo de hilos (threading) para que la aplicación no se congele.

Despliegue: Empaquetar la aplicación final en un ejecutable .exe usando PyInstaller.


2. Ignacio López: Desarrollador Backend & Especialista en IA / RAG
   
Área de trabajo principal: rag_core.py, scripts de procesamiento de documentos y conexión con Ollama.

Responsabilidades:

Motor RAG: Diseñar e implementar la búsqueda léxica (BM25) y la recuperación de información.

Integración de Modelos: Configurar, optimizar y conectar el modelo llama3.2 mediante Ollama.

Ingeniería de Prompts: Crear los prompts del sistema para que el modelo responda con precisión a partir de los datos locales sin inventar información.

Tratamiento de Datos: Manejar la lectura, fragmentación (chunking) e indexación de archivos locales (PDFs, TXT, etc.).


3. Josué García Desarrollador Frontend & Diseñador UX/UI

Área de trabajo principal: interface.html, hojas de estilo (CSS) y lógica de interfaz (JavaScript).

Responsabilidades:

Diseño Visual (UI): Diseñar la interfaz gráfica, paleta de colores, tipografías e identidad visual de la aplicación.

Experiencia de Usuario (UX): Crear el flujo de navegación del chat, animaciones de carga, alertas y respuestas dinámicas.

Desarrollo Web: Programar la lógica interactiva en JS (teclado en pantalla del PIN, entrada/salida del chat, estados de error).

Conexión con la API: Enlazar las acciones de la interfaz visual con las funciones de Python a través de pywebview.api.

## Metodología de Trabajo del Equipo
El desarrollo del proyecto se ejecutó bajo la metodología Scrum combinada con prácticas de DevOps:

Gestión de Sprints: Iteraciones cortas de desarrollo enfocadas en la entrega de módulos funcionales.

Control de Versiones: Flujo de trabajo basado en GitFlow (main para la versión estable de producción, develop para integración y ramas feature/ para nuevas características).

Seguimiento de Tareas: Tableros Kanban para la asignación de responsabilidades, control de incidencias y monitoreo de avances.

## Arquitectura de la Solución
La solución utiliza una arquitectura híbrida y desacoplada que combina la ligereza de una interfaz web local (interface_2.html) renderizada a través de pywebview, con un entorno ejecutable en Python (main_2.py) encargado del procesamiento de datos, búsqueda semántica e inferencia de Inteligencia Artificial mediante Ollama.


