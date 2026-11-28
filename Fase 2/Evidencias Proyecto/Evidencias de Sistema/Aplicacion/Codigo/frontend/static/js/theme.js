// Tema claro u oscuro. Se carga en <head> (sin defer) para aplicar el tema antes de dibujar la página
// y evitar un destello. La elección se guarda solo en este navegador.
(() => {
  const KEY = 'vexa-theme';
  const read = () => { try { return localStorage.getItem(KEY); } catch (_) { return null; } };
  const save = value => { try { localStorage.setItem(KEY, value); } catch (_) { /* modo privado: no se recuerda */ } };
  const apply = theme => {
    document.documentElement.dataset.theme = theme === 'light' ? 'light' : 'dark';
    document.querySelectorAll('[data-theme-toggle]').forEach(button => {
      const light = document.documentElement.dataset.theme === 'light';
      button.setAttribute('aria-pressed', light ? 'true' : 'false');
      button.title = light ? 'Cambiar a tema oscuro' : 'Cambiar a tema claro';
      const icon = button.querySelector('[data-theme-icon]');
      if (icon) icon.textContent = light ? '☾' : '☀';
    });
  };
  apply(read());
  document.addEventListener('DOMContentLoaded', () => {
    apply(document.documentElement.dataset.theme);
    document.querySelectorAll('[data-theme-toggle]').forEach(button => button.addEventListener('click', () => {
      const next = document.documentElement.dataset.theme === 'light' ? 'dark' : 'light';
      save(next);
      apply(next);
    }));
  });
})();
