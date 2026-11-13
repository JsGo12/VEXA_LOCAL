// Asistente transversal: conversaciones propias, filtro por expediente y fuentes con expediente/documento/página.
(() => {
  const app = document.getElementById('assistantApp');
  if (!app) return;
  const urls = app.dataset;
  const list = document.getElementById('conversationList');
  const messages = document.getElementById('assistantMessages');
  const form = document.getElementById('assistantForm');
  const input = document.getElementById('assistantInput');
  const title = document.getElementById('conversationTitle');
  const deleteButton = document.getElementById('deleteConversation');
  let current = null;

  const convUrl = (id, suffix) => `${urls.baseUrl}/${id}/${suffix}`;
  const caseUrl = id => urls.caseUrl.replace(/0$/, String(id));
  const documentUrl = id => urls.documentUrl.replace(/0$/, String(id));

  const pageLabel = s => (s.page_start ? (s.page_end && s.page_end !== s.page_start ? ` · págs. ${s.page_start}-${s.page_end}` : ` · pág. ${s.page_start}`) : '');

  const renderSources = (block, sources) => {
    if (!sources?.length) return;
    const box = document.createElement('div');
    box.className = 'firm-sources';
    const heading = document.createElement('span');
    heading.className = 'eyebrow';
    heading.textContent = 'FUENTES';
    box.appendChild(heading);
    sources.forEach(s => {
      const row = document.createElement('div');
      row.className = `firm-source firm-source-${s.source_type}`;
      const caseLink = document.createElement('a');
      caseLink.href = caseUrl(s.case_id);
      caseLink.className = 'source-case';
      caseLink.textContent = s.case_label || `Caso #${s.case_id}`;
      row.appendChild(caseLink);
      const doc = document.createElement(s.downloadable ? 'a' : 'span');
      doc.className = 'source-doc';
      if (s.downloadable) doc.href = documentUrl(s.document_id);
      doc.textContent = `${s.label}${pageLabel(s)}`;
      row.appendChild(doc);
      box.appendChild(row);
    });
    block.appendChild(box);
  };

  const addMessage = (text, type, sources = [], redacted = false) => {
    const block = document.createElement('article');
    block.className = `chat-message ${type}${redacted ? ' redacted' : ''}`;
    const body = document.createElement('p');
    body.textContent = text;
    block.appendChild(body);
    renderSources(block, sources);
    messages.appendChild(block);
    messages.scrollTop = messages.scrollHeight;
    return block;
  };

  const loadConversations = async () => {
    const data = await (await fetch(urls.conversationsUrl)).json();
    list.replaceChildren();
    (data.conversations || []).forEach(c => {
      const item = document.createElement('li');
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = c.title;
      button.className = c.id === current ? 'active' : '';
      button.addEventListener('click', () => openConversation(c.id, c.title));
      item.appendChild(button);
      list.appendChild(item);
    });
  };

  const openConversation = async (id, label) => {
    current = id;
    title.textContent = label || 'Conversación';
    deleteButton.hidden = false;
    messages.replaceChildren();
    const data = await (await fetch(convUrl(id, 'messages'))).json();
    (data.messages || []).forEach(m => addMessage(m.content, m.role === 'user' ? 'user-message' : 'assistant-message', m.sources, m.redacted));
    loadConversations();
  };

  const selectedCases = () => {
    const ids = [...document.querySelectorAll('#scopeList input:checked')].map(i => Number(i.value));
    return ids.length ? ids : null;
  };

  const loadScope = async () => {
    const data = await (await fetch(urls.scopeUrl)).json();
    const box = document.getElementById('scopeList');
    box.replaceChildren();
    document.getElementById('scopeCount').textContent = String((data.cases || []).length);
    (data.cases || []).forEach(c => {
      const label = document.createElement('label');
      label.className = 'check-row';
      const check = document.createElement('input');
      check.type = 'checkbox';
      check.value = c.id;
      const text = document.createElement('span');
      text.textContent = `${c.label} (${c.documents} doc.)`;
      label.append(check, text);
      box.appendChild(label);
    });
    if (!(data.cases || []).length) {
      const p = document.createElement('p');
      p.className = 'empty-inline';
      p.textContent = 'Sin expedientes autorizados para el asistente.';
      box.appendChild(p);
    }
  };

  document.getElementById('newConversation').addEventListener('click', () => {
    current = null;
    title.textContent = 'Nueva consulta';
    deleteButton.hidden = true;
    messages.replaceChildren();
    input.focus();
    loadConversations();
  });

  deleteButton.addEventListener('click', async () => {
    if (!current || !confirm('¿Eliminar esta conversación? No se puede deshacer.')) return;
    await Vexa.postJSON(convUrl(current, 'delete'));
    document.getElementById('newConversation').click();
  });

  form.addEventListener('submit', async event => {
    event.preventDefault();
    const question = input.value.trim();
    if (!question) return;
    input.value = '';
    input.disabled = true;
    addMessage(question, 'user-message');
    const wait = addMessage('Buscando en los expedientes autorizados…', 'assistant-message');
    try {
      if (!current) {
        const created = await Vexa.postJSON(urls.createUrl, { title: question });
        if (!created.ok) throw await Vexa.errorFrom(created);
        current = (await created.json()).id;
        title.textContent = question.slice(0, 80);
        deleteButton.hidden = false;
      }
      const body = { question };
      const cases = selectedCases();
      if (cases) body.case_ids = cases;
      const response = await Vexa.postJSON(convUrl(current, 'ask'), body);
      if (!response.ok) throw await Vexa.errorFrom(response);
      let block = null, answer = '';
      await Vexa.readNdjson(response, item => {
        if (item.type === 'status' && !block) wait.querySelector('p').textContent = item.text;
        if (item.type === 'delta') {
          if (!block) { wait.remove(); block = addMessage('', 'assistant-message'); }
          answer += item.text || '';
          block.querySelector('p').textContent = answer;
          messages.scrollTop = messages.scrollHeight;
        }
        if (item.type === 'done') {
          if (!block) { wait.remove(); block = addMessage('', 'assistant-message'); }
          renderSources(block, item.sources);
        }
      });
      loadConversations();
    } catch (error) {
      wait.remove();
      addMessage(error.message, 'assistant-message');
    } finally {
      input.disabled = false;
      input.focus();
    }
  });

  (async () => {
    const status = document.getElementById('ollamaStatus');
    try {
      const result = await (await fetch(urls.ollamaUrl)).json();
      status.className = `ollama-status ${result.ready ? 'ready' : (result.connected ? 'missing-model' : 'offline')}`;
      status.querySelector('span').textContent = result.message;
    } catch (_) {
      status.className = 'ollama-status offline';
      status.querySelector('span').textContent = 'No se pudo verificar Ollama';
    }
  })();
  loadConversations();
  loadScope();
})();
