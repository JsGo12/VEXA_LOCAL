// Botón «Imprimir / PDF»: abre el diálogo de impresión del navegador (ahí se elige «Guardar como PDF»).
document.querySelectorAll('[data-print]').forEach(button => button.addEventListener('click', () => window.print()));
