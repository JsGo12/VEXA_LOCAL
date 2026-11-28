// Visor de documentos de las citas: abre el PDF en la página citada (o el texto) dentro de VEXA,
// en una ventana emergente, sin salir del chat. Los enlaces con data-viewer lo usan.
window.Vexa = window.Vexa || {};

(() => {
  let dialog = null, frame = null, title = null, download = null;

  const build = () => {
    dialog = document.createElement('dialog');
    dialog.className = 'doc-viewer';
    const bar = document.createElement('div');
    bar.className = 'doc-viewer-bar';
    title = document.createElement('strong');
    download = document.createElement('a');
    download.className = 'text-link';
    download.textContent = 'Descargar';
    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'button button-quiet';
    close.textContent = 'Cerrar';
    close.addEventListener('click', () => dialog.close());
    bar.append(title, download, close);
    frame = document.createElement('iframe');
    frame.title = 'Documento citado';
    dialog.append(bar, frame);
    dialog.addEventListener('close', () => { frame.src = 'about:blank'; });
    document.body.appendChild(dialog);
  };

  // url: /documents/<id>/ver#page=N · label: texto de la cita
  Vexa.openDocument = (url, label) => {
    if (!dialog) build();
    title.textContent = label || 'Documento';
    download.href = url.replace(/\/ver(#.*)?$/, '');
    frame.src = 'about:blank';                  // así un cambio solo de #page vuelve a cargar
    requestAnimationFrame(() => { frame.src = url; });
    if (!dialog.open) dialog.showModal();
  };

  document.addEventListener('click', event => {
    const link = event.target.closest('a[data-viewer]');
    if (!link || event.ctrlKey || event.metaKey || event.shiftKey) return;
    event.preventDefault();
    Vexa.openDocument(link.getAttribute('href'), link.dataset.label || link.textContent);
  });
})();

// Lista de fuentes de una respuesta del chat: cada una enlaza al documento si el usuario puede abrirlo.
// links: [{label, url, viewer}] (del servidor) o, si faltan, solo los textos.
Vexa.renderSourceLinks = (block, links, labels = []) => {
  const items = links?.length ? links : labels.map(label => ({ label }));
  if (!items.length) return;
  const refs = document.createElement('div');
  refs.className = 'sources';
  refs.append('Fuentes: ');
  items.forEach((item, i) => {
    if (i) refs.append(' | ');
    if (item.url) {
      const a = document.createElement('a');
      a.href = item.url;
      a.className = 'source-link';
      a.textContent = item.label;
      a.dataset.label = item.label;
      if (item.viewer) a.dataset.viewer = '';
      refs.appendChild(a);
    } else {
      refs.append(item.label);
    }
  });
  block.appendChild(refs);
};
