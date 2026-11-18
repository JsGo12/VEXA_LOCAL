// Chat individual del expediente: historial, consulta en streaming, estado de indexación y resumen IA.
(() => {
  const root = document.getElementById('caseWorkspace');
  if (!root) return;
  const urls = root.dataset;
  const form = document.getElementById('questionForm');
  const input = document.getElementById('questionInput');
  const messages = document.getElementById('chatMessages');

  const addMessage = (text, type, sources = []) => {
    const block = document.createElement('article');
    block.className = `chat-message ${type}`;
    const body = document.createElement('p');
    body.textContent = text;
    block.appendChild(body);
    if (sources.length) {
      const refs = document.createElement('div');
      refs.className = 'sources';
      refs.textContent = 'Fuentes: ' + sources.join(' | ');
      block.appendChild(refs);
    }
    messages.appendChild(block);
    messages.scrollTop = messages.scrollHeight;
    return block;
  };

  const button = form.querySelector('button');
  let query = null;                                   // consulta en curso (se puede detener)

  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (query) { query.stop(); return; }              // el botón dice "Detener" mientras responde
    const question = input.value.trim();
    if (!question) return;
    addMessage(question, 'user-message');
    input.value = '';
    input.disabled = true;
    query = Vexa.stoppable();
    Vexa.setBusyButton(button, true);
    const wait = addMessage('Buscando antecedentes y consultando el modelo local...', 'assistant-message');
    let block = null, answer = '';
    try {
      const response = await Vexa.postJSON(urls.chatUrl, { question }, query.signal);
      query.touch();
      if (!response.ok) throw await Vexa.errorFrom(response);
      if (response.headers.get('content-type')?.includes('application/x-ndjson')) {
        let paragraph = null;
        await Vexa.readNdjson(response, item => {
          if (item.type === 'delta') {
            if (!block) {
              wait.remove();
              block = addMessage('', 'assistant-message');
              paragraph = block.querySelector('p');
            }
            answer += item.text || '';
            paragraph.textContent = answer;
            messages.scrollTop = messages.scrollHeight;
          } else if (item.type === 'done') {
            if (!block) { wait.remove(); block = addMessage('', 'assistant-message'); }
            if (item.sources?.length) {
              const refs = document.createElement('div');
              refs.className = 'sources';
              refs.textContent = 'Fuentes: ' + item.sources.join(' | ');
              block.appendChild(refs);
            }
          } else if (item.type === 'progress' && !block) {
            wait.querySelector('p').textContent = `Revisando el expediente completo… bloque ${Math.min(item.done + 1, item.total)} de ${item.total}`;
          }
        }, query.touch);
      } else {
        const result = await response.json();
        if (!result.ok) throw new Error(result.error || 'No se pudo completar la consulta.');
        wait.remove();
        addMessage(result.answer, 'assistant-message', result.sources || []);
      }
    } catch (error) {
      wait.remove();
      if (query.reason) {
        const partial = Boolean(block && answer.trim());
        Vexa.addChatNote(partial ? block : addMessage('', 'assistant-message stopped'), Vexa.stoppedText(query, partial));
      } else {
        addMessage(error.message, 'assistant-message');
      }
    } finally {
      query.finish();
      query = null;
      Vexa.setBusyButton(button, false);
      input.disabled = false;
      input.focus();
    }
  });

  // Esc detiene la respuesta (salvo que haya una ventana abierta: ahí Esc la cierra).
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && query && !document.querySelector('dialog[open]')) query.stop();
  });

  document.querySelectorAll('.suggestion-list button').forEach(button => button.addEventListener('click', () => {
    input.value = button.dataset.question;
    form.requestSubmit();
  }));

  const loadHistory = async () => {
    try {
      const data = await (await fetch(urls.historyUrl)).json();
      (data.messages || []).forEach(m => addMessage(m.content, m.role === 'user' ? 'user-message' : 'assistant-message',
        m.sources ? m.sources.split(' | ') : []));
    } catch (_) { /* el historial es opcional */ }
  };

  const pollPrep = async () => {
    const bar = document.getElementById('prepBar');
    try {
      const s = await (await fetch(urls.statusUrl)).json();
      if (s.state === 'running') {
        bar.hidden = false;
        document.getElementById('prepFill').style.width = Math.round(s.progress * 100) + '%';
        document.getElementById('prepText').textContent = `${s.message} · ${Math.round(s.progress * 100)}%`;
        setTimeout(pollPrep, 1000);
        return;
      }
      bar.hidden = s.state !== 'error';
      if (s.state === 'error') document.getElementById('prepText').textContent = s.message;
    } catch (_) { /* reintento innecesario */ }
    input.disabled = false;
  };

  const pollSummary = async (n = 0) => {
    try {
      const s = await (await fetch(urls.summaryUrl)).json();
      if (s.summary) {
        const el = document.getElementById('aiSummary');
        el.hidden = false;
        el.textContent = 'Resumen automático (IA): ' + s.summary;
        return;
      }
    } catch (_) { /* se vuelve a intentar */ }
    if (n < 40) setTimeout(() => pollSummary(n + 1), 5000);
  };

  loadHistory(); pollPrep(); pollSummary(); Vexa.checkOllama(urls.ollamaUrl);
})();
