// Formulario de avance: el motivo de cierre solo aparece (y es obligatorio) cuando el estado es «Cerrado».
// Con «Completado» el avance se lleva a 100 %; con otros motivos se conserva el porcentaje real.
(() => {
  document.querySelectorAll('[data-close-reason]').forEach(field => {
    const form = field.closest('form');
    const status = form?.querySelector('select[name="status"]');
    const reason = field.querySelector('select');
    const progress = form?.querySelector('input[name="progress"]');
    if (!status || !reason) return;
    const sync = () => {
      const closing = status.value === 'cerrado';
      field.hidden = !closing;
      reason.required = closing;
      if (!closing) reason.value = '';
      if (closing && reason.value === 'completado' && progress) progress.value = 100;
    };
    status.addEventListener('change', sync);
    reason.addEventListener('change', sync);
    form.addEventListener('reset', () => setTimeout(sync, 0));
    sync();
  });
})();
