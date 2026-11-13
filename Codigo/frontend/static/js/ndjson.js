// Utilidades compartidas: lectura de respuestas NDJSON en streaming y peticiones con CSRF.
window.Vexa = window.Vexa || {};

Vexa.csrf = () => document.querySelector('meta[name="csrf-token"]')?.content || '';

Vexa.postJSON = (url, body) => fetch(url, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': Vexa.csrf() },
  body: JSON.stringify(body || {}),
});

// Consume una respuesta application/x-ndjson llamando a onEvent(evento) por cada línea.
// Lanza un Error si el servidor envía {"type":"error"} o si el flujo termina sin "done".
Vexa.readNdjson = async (response, onEvent) => {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let pending = '', completed = false;
  const handle = line => {
    if (!line.trim()) return;
    const item = JSON.parse(line);
    if (item.type === 'error') throw new Error(item.error || 'No se pudo completar la consulta.');
    if (item.type === 'done') completed = true;
    onEvent(item);
  };
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    pending += decoder.decode(value, { stream: true });
    const lines = pending.split('\n');
    pending = lines.pop();
    lines.forEach(handle);
  }
  pending += decoder.decode();
  if (pending.trim()) handle(pending);
  if (!completed) throw new Error('La respuesta se interrumpió antes de terminar. Inténtalo otra vez.');
};

// Muestra el error devuelto por el backend (JSON) o uno genérico.
Vexa.errorFrom = async response => {
  try { const data = await response.json(); return new Error(data.error || 'No se pudo completar la consulta.'); }
  catch (_) { return new Error('No se pudo completar la consulta.'); }
};
