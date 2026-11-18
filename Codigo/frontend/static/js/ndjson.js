// Utilidades compartidas: lectura de respuestas NDJSON en streaming y peticiones con CSRF.
window.Vexa = window.Vexa || {};

Vexa.csrf = () => document.querySelector('meta[name="csrf-token"]')?.content || '';

Vexa.postJSON = (url, body, signal) => fetch(url, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': Vexa.csrf() },
  body: JSON.stringify(body || {}),
  signal,
});

// Consume una respuesta application/x-ndjson llamando a onEvent(evento) por cada línea.
// Lanza un Error si el servidor envía {"type":"error"} o si el flujo termina sin "done".
// onActivity (opcional) se llama cada vez que llegan datos, aunque la línea aún no esté completa.
Vexa.readNdjson = async (response, onEvent, onActivity) => {
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
    if (onActivity) onActivity();
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

// Consulta al modelo que se puede detener. Devuelve { signal, reason, touch, stop, finish }:
// pasa `signal` a fetch, llama a `touch()` cada vez que llegan datos y a `finish()` al terminar.
// Si pasan CHAT_IDLE_MS sin recibir nada, la consulta se corta sola (reason = 'timeout'); al
// cortarse, el servidor deja de generar y la respuesta incompleta no se guarda en el historial.
Vexa.CHAT_IDLE_MS = 3 * 60 * 1000;
Vexa.stoppable = (idleMs = Vexa.CHAT_IDLE_MS) => {
  const controller = new AbortController();
  let timer = null;
  const query = { signal: controller.signal, reason: null };
  const abort = reason => {
    if (query.reason) return;
    query.reason = reason;
    clearTimeout(timer);
    controller.abort();
  };
  query.touch = () => { clearTimeout(timer); timer = setTimeout(() => abort('timeout'), idleMs); };
  query.stop = () => abort('user');
  query.finish = () => clearTimeout(timer);
  query.touch();
  return query;
};

// Texto que se muestra cuando una consulta se cortó (por el usuario o por el tiempo límite).
Vexa.stoppedText = (query, hasPartial) => {
  const minutes = Math.round(Vexa.CHAT_IDLE_MS / 60000);
  if (query.reason === 'timeout') {
    return `El modelo local no respondió en ${minutes} minutos y la consulta se detuvo. Puede pasar si el ` +
      'PC servidor está ocupado o el modelo se está cargando. Inténtalo de nuevo o haz una pregunta más concreta.' +
      (hasPartial ? ' Lo de arriba quedó incompleto y no se guardó en el historial.' : '');
  }
  return hasPartial ? 'Respuesta detenida. Quedó incompleta y no se guardó en el historial.' : 'Consulta detenida.';
};

// Cambia el botón del formulario entre "Consultar" y "Detener".
Vexa.setBusyButton = (button, busy) => {
  button.textContent = busy ? 'Detener' : 'Consultar';
  button.classList.toggle('button-primary', !busy);
  button.classList.toggle('button-stop', busy);
  button.title = busy ? 'Detener la respuesta (Esc)' : '';
};
