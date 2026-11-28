// Ventanas emergentes (<dialog>): un botón con data-open-dialog="id" abre la ventana; se cierra con
// los botones data-close-dialog, con Esc o haciendo clic fuera del recuadro. Sin scripts en línea (CSP).
(() => {
  document.querySelectorAll('[data-open-dialog]').forEach(trigger => {
    const dialog = document.getElementById(trigger.dataset.openDialog);
    if (!dialog || typeof dialog.showModal !== 'function') return;
    trigger.addEventListener('click', () => dialog.showModal());
  });
  document.querySelectorAll('dialog').forEach(dialog => {
    dialog.querySelectorAll('[data-close-dialog]').forEach(button => button.addEventListener('click', () => dialog.close()));
    // El contenido vive en un contenedor interno; un clic directo sobre <dialog> es un clic en el fondo.
    dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });
    // Cerrar sin guardar (Cancelar, ✕, Esc o clic fuera) descarta lo que se cambió en la ventana.
    dialog.addEventListener('close', () => dialog.querySelectorAll('form').forEach(form => form.reset()));
  });
})();
