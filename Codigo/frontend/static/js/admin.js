// Filtra el selector de responsable según el tipo de asignación (abogado/a o equipo).
document.querySelectorAll('.js-assignment-type').forEach(kindSelect => {
  const assignee = document.getElementById(kindSelect.dataset.target);
  if (!assignee) return;
  const filter = () => {
    const kind = kindSelect.value;
    [...assignee.options].forEach(option => { option.hidden = option.dataset.kind && option.dataset.kind !== kind; });
    const first = [...assignee.options].find(option => option.dataset.kind === kind);
    assignee.value = first ? first.value : '';
  };
  kindSelect.addEventListener('change', filter);
  filter();
});

// Pestañas del panel: cambian sin recargar y dejan la pestaña en la URL (?tab=…) para volver a ella.
(() => {
  const tabs = [...document.querySelectorAll('.admin-tab[data-tab]')];
  if (!tabs.length) return;
  const show = name => {
    tabs.forEach(tab => {
      const active = tab.dataset.tab === name;
      tab.classList.toggle('is-active', active);
      tab.setAttribute('aria-selected', active ? 'true' : 'false');
      const panel = document.getElementById(`tab-${tab.dataset.tab}`);
      if (panel) panel.hidden = !active;
    });
  };
  tabs.forEach(tab => tab.addEventListener('click', event => {
    if (event.ctrlKey || event.metaKey || event.shiftKey) return;   // permite abrir en otra pestaña
    event.preventDefault();
    show(tab.dataset.tab);
    try { history.replaceState(null, '', tab.href); } catch (_) { /* sin historial: igual funciona */ }
  }));
})();

// Selector de personas: contador de seleccionados, búsqueda y botones Todos / Ninguno.
document.querySelectorAll('[data-picker]').forEach(picker => {
  const boxes = [...picker.querySelectorAll('input[type=checkbox]')];
  const count = picker.querySelector('[data-picker-count]');
  const search = picker.querySelector('[data-picker-search]');
  const empty = picker.querySelector('[data-picker-empty]');
  const items = [...picker.querySelectorAll('[data-picker-item]')];
  const refresh = () => {
    const n = boxes.filter(box => box.checked).length;
    if (count) count.textContent = `${n} seleccionado(s)`;
  };
  boxes.forEach(box => box.addEventListener('change', refresh));
  const visible = () => items.filter(item => !item.hidden).map(item => item.querySelector('input'));
  picker.querySelector('[data-picker-all]')?.addEventListener('click', () => { visible().forEach(b => { b.checked = true; }); refresh(); });
  picker.querySelector('[data-picker-none]')?.addEventListener('click', () => { visible().forEach(b => { b.checked = false; }); refresh(); });
  search?.addEventListener('input', () => {
    const term = search.value.trim().toLowerCase();
    let shown = 0;
    items.forEach(item => { item.hidden = term && !item.dataset.search.includes(term); if (!item.hidden) shown += 1; });
    if (empty) empty.hidden = shown > 0;
  });
  // Al cancelar, el formulario vuelve a su estado original (el contador también).
  picker.closest('form')?.addEventListener('reset', () => setTimeout(refresh, 0));
  refresh();
});
