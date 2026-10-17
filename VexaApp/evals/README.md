# Evaluación local del RAG

`demo.json` y `fixtures/contrato_demo.txt` contienen datos completamente ficticios para comprobar el flujo sin usar expedientes reales. Desde la raíz del repositorio, con Ollama iniciado y un modelo de chat instalado:

```powershell
python .\eval_rag.py .\evals\demo.json --output "$env:USERPROFILE\.vexa_local\evaluaciones\demo.json"
```

El evaluador construye el índice desde cero, ejecuta las mismas rutas de búsqueda y generación que usa el chat, y guarda un JSON con:

- **Recall de recuperación:** proporción de fuentes esperadas que entraron al contexto recuperado.
- **Recall de citas:** proporción de fuentes esperadas que la respuesta devuelve como fuente.
- **Cobertura de términos esperados:** coincidencias literales, útiles para cifras, nombres y expresiones exactas. No juzga por sí sola si la respuesta es semánticamente correcta.
- **Abstención:** compara si VEXA respondió con una frase de “no encontré” cuando el conjunto marca que la respuesta no está.
- **Tiempo:** milisegundos por pregunta y tiempo separado de indexación. Incluye las llamadas locales al modelo.

Duplica `demo.json` para crear tu conjunto y cambia `documents` y `questions`. Las rutas relativas se resuelven desde la carpeta del JSON. Cada pregunta requiere un `id` único y un `question`; `expected_sources` y `expected_terms` son listas de textos. Las fuentes esperadas se comparan como subcadenas sin distinguir mayúsculas. Para preguntas sin respuesta en los documentos, usa listas vacías y `"expected_no_answer": true`.

El índice no usa ni modifica la base de producción. Ollama atiende las solicitudes localmente en `localhost:11434`; el evaluador no envía documentos a servicios externos. El JSON resultante guarda respuestas y nombres de documentos, así que almacénalo dentro de `.vexa_local` o en otra ubicación protegida. Usa documentos ficticios en cualquier conjunto que compartas o subas a GitHub.
