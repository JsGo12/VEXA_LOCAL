// Subida de documentos: zona para arrastrar y soltar, lista de archivos elegidos y barra de progreso.
// Mejora cualquier <input type="file"> de VEXA; sin JavaScript el formulario funciona igual que antes.
(() => {
  const ALLOWED = ['pdf', 'docx', 'xlsx', 'pptx', 'txt', 'csv'];
  const human = bytes => bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1048576).toFixed(1)} MB`;
  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text) n.textContent = text; return n; };

  document.querySelectorAll('form input[type="file"]').forEach(input => {
    const form = input.form;
    if (!form || input.dataset.enhanced) return;
    input.dataset.enhanced = '1';

    // Zona de arrastre alrededor del campo (el input queda dentro, invisible pero accesible).
    const zone = el('label', 'dropzone');
    const icon = el('span', 'dropzone-icon', '⤒');
    const text = el('span', 'dropzone-text');
    text.append(el('strong', null, 'Arrastra los archivos aquí'), el('small', null, 'o haz clic para elegirlos · PDF, DOCX, XLSX, PPTX, TXT o CSV'));
    input.parentNode.insertBefore(zone, input);
    zone.append(icon, text, input);
    const list = el('ul', 'file-list');
    zone.after(list);

    const render = () => {
      list.replaceChildren();
      [...input.files].forEach(file => {
        const ext = file.name.includes('.') ? file.name.split('.').pop().toLowerCase() : '';
        const item = el('li', ALLOWED.includes(ext) ? 'file-item' : 'file-item is-bad');
        item.append(el('span', 'file-ext', (ext || '?').toUpperCase()), el('span', 'file-name', file.name),
          el('small', null, ALLOWED.includes(ext) ? human(file.size) : 'formato no admitido'));
        list.appendChild(item);
      });
      zone.classList.toggle('has-files', input.files.length > 0);
    };
    input.addEventListener('change', render);
    ['dragenter', 'dragover'].forEach(type => zone.addEventListener(type, event => { event.preventDefault(); zone.classList.add('is-over'); }));
    ['dragleave', 'drop'].forEach(type => zone.addEventListener(type, () => zone.classList.remove('is-over')));
    zone.addEventListener('drop', event => {
      event.preventDefault();
      if (!event.dataTransfer?.files?.length) return;
      const transfer = new DataTransfer();
      [...(input.multiple ? event.dataTransfer.files : [event.dataTransfer.files[0]])].forEach(f => transfer.items.add(f));
      input.files = transfer.files;
      render();
    });
    form.addEventListener('reset', () => setTimeout(render, 0));

    // Envío con barra de progreso.
    form.addEventListener('submit', event => {
      if (!input.files.length || form.dataset.uploading) return;
      event.preventDefault();
      form.dataset.uploading = '1';
      const bar = el('div', 'upload-progress');
      const fill = el('div', 'upload-fill');
      const label = el('span', 'upload-label', 'Subiendo… 0 %');
      bar.append(el('div', 'upload-track'), label);
      bar.firstChild.appendChild(fill);
      list.after(bar);
      form.querySelectorAll('button').forEach(b => { b.disabled = true; });

      const xhr = new XMLHttpRequest();
      xhr.open('POST', form.action);
      xhr.setRequestHeader('X-Requested-With', 'vexa-upload');
      xhr.upload.addEventListener('progress', e => {
        if (!e.lengthComputable) return;
        const pct = Math.round((e.loaded / e.total) * 100);
        fill.style.width = `${pct}%`;
        label.textContent = pct < 100 ? `Subiendo… ${pct} %` : 'Cifrando y guardando…';
      });
      const fail = message => {
        label.textContent = message;
        bar.classList.add('is-error');
        delete form.dataset.uploading;
        form.querySelectorAll('button').forEach(b => { b.disabled = false; });
      };
      xhr.addEventListener('load', () => {
        let data = null;
        try { data = JSON.parse(xhr.responseText); } catch (_) { /* respuesta HTML */ }
        if (data?.redirect) { window.location.assign(data.redirect); return; }
        if (xhr.status >= 200 && xhr.status < 400) { window.location.reload(); return; }
        fail(xhr.status === 413 ? 'Los archivos superan el tamaño permitido.' : 'No se pudo subir. Revisa los archivos e inténtalo otra vez.');
      });
      xhr.addEventListener('error', () => fail('Se perdió la conexión con el servidor.'));
      xhr.send(new FormData(form));
    });
  });
})();
