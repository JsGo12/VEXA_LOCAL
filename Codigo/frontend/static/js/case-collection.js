// Listas de casos: búsqueda, filtros (estado, plazo, responsable), orden y vista tarjetas/tabla.
// La vista elegida se recuerda en este navegador.
(() => {
  const readView = key => { try { return localStorage.getItem(`vexa-view-${key}`); } catch (_) { return null; } };
  const saveView = (key, view) => { try { localStorage.setItem(`vexa-view-${key}`, view); } catch (_) { /* sin almacenamiento */ } };
  const compare = {
    due: (a, b) => a.dataset.due.localeCompare(b.dataset.due),
    'due-desc': (a, b) => b.dataset.due.localeCompare(a.dataset.due),
    progress: (a, b) => Number(a.dataset.progress) - Number(b.dataset.progress),
    'progress-desc': (a, b) => Number(b.dataset.progress) - Number(a.dataset.progress),
    title: (a, b) => a.dataset.name.localeCompare(b.dataset.name, 'es'),
  };

  document.querySelectorAll('[data-collection]').forEach(root => {
    const key = root.dataset.collection;
    const panels = [...root.querySelectorAll('[data-view-panel]')];
    const filters = [...root.querySelectorAll('[data-filter]')];
    const sorter = root.querySelector('[data-sort]');
    const count = root.querySelector('[data-count]');
    const empty = root.querySelector('[data-empty]');
    const total = root.querySelectorAll('[data-view-panel="cards"] [data-item]').length;

    const apply = () => {
      const wanted = Object.fromEntries(filters.map(f => [f.dataset.filter, f.value.trim().toLowerCase()]));
      let shown = 0;
      panels.forEach(panel => {
        const container = panel.matches('table, .table-wrap') ? panel.querySelector('tbody') : panel;
        const items = [...container.querySelectorAll(':scope > [data-item]')];
        items.sort(compare[sorter?.value || 'due']).forEach(item => {
          const ok = (!wanted.text || item.dataset.title.includes(wanted.text))
            && (!wanted.status || item.dataset.status === wanted.status)
            && (!wanted.deadline || item.dataset.deadline === wanted.deadline)
            && (!wanted.assignee || item.dataset.assignee === wanted.assignee);
          item.hidden = !ok;
          container.appendChild(item);                 // reordena en el DOM
          if (ok && panel.dataset.viewPanel === 'cards') shown += 1;
        });
      });
      if (count) count.textContent = shown === total ? `${total} caso(s)` : `${shown} de ${total} caso(s)`;
      if (empty) empty.hidden = shown > 0;
    };

    const setView = view => {
      panels.forEach(panel => { panel.hidden = panel.dataset.viewPanel !== view; });
      root.querySelectorAll('[data-view]').forEach(button => {
        const active = button.dataset.view === view;
        button.classList.toggle('is-active', active);
        button.setAttribute('aria-pressed', active ? 'true' : 'false');
      });
    };

    filters.forEach(f => f.addEventListener(f.tagName === 'INPUT' ? 'input' : 'change', apply));
    sorter?.addEventListener('change', apply);
    root.querySelectorAll('[data-view]').forEach(button => button.addEventListener('click', () => {
      setView(button.dataset.view);
      saveView(key, button.dataset.view);
    }));
    setView(readView(key) === 'table' ? 'table' : 'cards');
    apply();
  });
})();
