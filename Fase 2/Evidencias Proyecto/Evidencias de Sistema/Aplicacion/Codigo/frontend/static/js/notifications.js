// Campana de notificaciones: actualiza el número de avisos sin leer cada minuto (sin recargar la página).
(() => {
  const bell = document.querySelector('.notif-bell[data-notif-url]');
  const badge = bell?.querySelector('[data-notif-badge]');
  if (!bell || !badge) return;
  const refresh = async () => {
    if (document.hidden) return;
    try {
      const response = await fetch(bell.dataset.notifUrl, { headers: { Accept: 'application/json', 'X-Vexa-Background': '1' } });
      if (!response.ok) return;
      const { unread } = await response.json();
      badge.hidden = !unread;
      badge.textContent = unread > 99 ? '99+' : String(unread);
      bell.setAttribute('aria-label', unread ? `Notificaciones: ${unread} sin leer` : 'Notificaciones');
    } catch (_) { /* sin conexión: se reintenta en el próximo ciclo */ }
  };
  setInterval(refresh, 60000);
  document.addEventListener('visibilitychange', refresh);
})();
