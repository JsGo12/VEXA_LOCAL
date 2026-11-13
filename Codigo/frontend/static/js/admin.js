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
