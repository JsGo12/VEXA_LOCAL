// Vista de Permisos: búsqueda en las listas laterales y selector de alcance (firma / equipo / caso).
(() => {
  document.querySelectorAll('[data-filter-list]').forEach(input => {
    const list = document.getElementById(input.dataset.filterList);
    if (!list) return;
    input.addEventListener('input', () => {
      const term = input.value.trim().toLowerCase();
      list.querySelectorAll('li[data-search]').forEach(item => { item.hidden = term && !item.dataset.search.includes(term); });
    });
  });

  document.querySelectorAll('[data-grant-form]').forEach(form => {
    const target = form.querySelector('[data-grant-target]');
    const select = target?.querySelector('select');
    if (!select) return;
    const sync = () => {
      const kind = form.querySelector('input[name="scope_type"]:checked')?.value || 'case';
      target.hidden = kind === 'firm';
      select.disabled = kind === 'firm';
      let first = null;
      select.querySelectorAll('optgroup').forEach(group => {
        const show = group.dataset.kind === kind;
        group.hidden = !show;
        group.querySelectorAll('option').forEach(option => { option.disabled = !show; if (show && !first) first = option; });
      });
      if (first && (select.selectedOptions[0]?.disabled ?? true)) select.value = first.value;
    };
    form.querySelectorAll('input[name="scope_type"]').forEach(radio => radio.addEventListener('change', sync));
    form.addEventListener('reset', () => setTimeout(sync, 0));
    sync();
  });
})();
