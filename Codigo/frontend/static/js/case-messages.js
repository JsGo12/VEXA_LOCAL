// Mensajes del equipo en el expediente: pestañas IA/Mensajes, envío sin recargar, mensajes rápidos y
// revisión de mensajes nuevos cada 15 s. Todo el texto se inserta con textContent.
(() => {
  const panel = document.querySelector('.team-panel[data-messages-url]');
  const tabs = [...document.querySelectorAll('[data-panel-tab]')];
  if (!panel || !tabs.length) return;
  const thread = panel.querySelector('[data-thread]');
  const form = panel.querySelector('[data-team-form]');
  const textarea = form.querySelector('textarea');
  const errorBox = panel.querySelector('[data-team-error]');
  const badge = document.querySelector('[data-messages-badge]');
  const csrf = () => form.querySelector('input[name="csrf_token"]').value;
  const lastId = () => Math.max(0, ...[...thread.querySelectorAll('[data-id]')].map(n => Number(n.dataset.id)));
  const visible = () => !panel.hidden && !document.hidden;
  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; };
  const ROLE = { admin: 'Administrador', chief_lawyer: 'Abogado/a jefe', lawyer: 'Abogado/a' };
  const initials = name => (name || '?').split(/\s+/).filter(Boolean).slice(0, 2).map(w => w[0]).join('').toUpperCase() || '?';

  const render = message => {
    if (thread.querySelector(`[data-id="${message.id}"]`)) return;
    thread.querySelector('[data-thread-empty]')?.remove();
    let node;
    if (message.kind === 'sistema') {
      node = el('div', 'msg-system');
      node.append(el('span', null, message.body), el('small', null, message.when));
    } else {
      node = el('article', message.mine ? 'msg is-mine' : 'msg');
      const bubble = el('div', 'msg-bubble');
      const meta = el('div', 'msg-meta');
      meta.append(el('strong', null, message.mine ? 'Tú' : message.author),
        el('small', null, `${ROLE[message.role] || ''} · ${message.when}`));
      bubble.append(meta, el('p', null, message.body));
      node.append(el('span', `msg-avatar role-${message.role || 'lawyer'}`, initials(message.author)), bubble);
    }
    node.dataset.id = message.id;
    thread.appendChild(node);
  };
  const scrollDown = () => { thread.scrollTop = thread.scrollHeight; };
  const setBadge = n => { if (!badge) return; badge.hidden = !n; badge.textContent = String(n); };

  const refresh = async (markRead = visible()) => {
    try {
      const url = `${panel.dataset.messagesUrl}?after=${lastId()}${markRead ? '&read=1' : ''}`;
      const data = await (await fetch(url, { headers: { Accept: 'application/json' } })).json();
      const atBottom = thread.scrollHeight - thread.scrollTop - thread.clientHeight < 40;
      (data.messages || []).forEach(render);
      if (atBottom || markRead) scrollDown();
      setBadge(markRead ? 0 : data.unread);
    } catch (_) { /* sin conexión: se reintenta */ }
  };

  const show = name => {
    tabs.forEach(tab => {
      const active = tab.dataset.panelTab === name;
      tab.classList.toggle('is-active', active);
      tab.setAttribute('aria-selected', active ? 'true' : 'false');
      const content = document.querySelector(`[data-panel-content="${tab.dataset.panelTab}"]`);
      if (content) content.hidden = !active;
    });
    if (name === 'mensajes') { scrollDown(); refresh(true); textarea.focus(); }
  };
  tabs.forEach(tab => tab.addEventListener('click', () => show(tab.dataset.panelTab)));

  panel.querySelectorAll('[data-quick]').forEach(chip => chip.addEventListener('click', () => {
    textarea.value = chip.dataset.quick;
    textarea.focus();
    textarea.setSelectionRange(textarea.value.length, textarea.value.length);
  }));

  textarea.addEventListener('keydown', event => {
    if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) { event.preventDefault(); form.requestSubmit(); }
  });

  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (!textarea.value.trim()) return;
    const body = new FormData(form);
    body.set('after', String(lastId()));
    const button = form.querySelector('button');
    button.disabled = true;
    errorBox.hidden = true;
    try {
      const response = await fetch(panel.dataset.sendUrl, {
        method: 'POST', body, headers: { 'X-Requested-With': 'vexa-fetch', 'X-CSRF-Token': csrf() } });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.error || 'No se pudo enviar el mensaje.');
      (data.messages || []).forEach(render);
      textarea.value = '';
      scrollDown();
    } catch (error) {
      errorBox.textContent = error.message || 'No se pudo enviar el mensaje.';
      errorBox.hidden = false;
    } finally {
      button.disabled = false;
      textarea.focus();
    }
  });

  if (!panel.hidden) scrollDown();
  setInterval(() => refresh(), 15000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
})();
