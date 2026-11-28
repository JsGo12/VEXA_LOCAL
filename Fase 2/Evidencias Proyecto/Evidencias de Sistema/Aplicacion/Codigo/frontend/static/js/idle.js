// Cierre de sesión por inactividad (VEXA_IDLE_MINUTES). Mientras la persona usa la página (teclado, mouse,
// scroll) se avisa al servidor cada pocos minutos; un minuto antes del límite aparece un aviso, y al llegar
// al límite se cierra la sesión. La actividad se comparte entre pestañas abiertas de VEXA.
(() => {
  const meta = document.querySelector('meta[name="vexa-idle-seconds"]');
  const limit = Number(meta?.content || 0) * 1000;
  if (!limit) return;
  const { pingUrl, expireUrl, loginUrl } = meta.dataset;
  const KEY = 'vexa-last-activity';
  const PING_EVERY = Math.min(5 * 60 * 1000, limit / 2);
  const WARN_BEFORE = Math.min(60 * 1000, limit / 4);
  const csrf = () => document.querySelector('meta[name="csrf-token"]')?.content || '';
  const post = url => fetch(url, { method: 'POST', headers: { 'X-CSRF-Token': csrf() } });

  let lastActivity = Date.now(), lastPing = Date.now(), lastShared = 0, banner = null, closing = false;

  const shared = () => {
    try { return Number(localStorage.getItem(KEY)) || 0; } catch (_) { return 0; }
  };
  const share = now => {
    if (now - lastShared < 5000) return;
    lastShared = now;
    try { localStorage.setItem(KEY, String(now)); } catch (_) { /* sin almacenamiento: solo esta pestaña */ }
  };

  const ping = () => {
    lastPing = Date.now();
    post(pingUrl).then(r => { if (r.status === 401) window.location.href = loginUrl; }).catch(() => {});
  };

  const hideBanner = () => { banner?.remove(); banner = null; };
  const showBanner = seconds => {
    if (!banner) {
      banner = document.createElement('div');
      banner.className = 'idle-banner';
      banner.setAttribute('role', 'alert');
      const text = document.createElement('span');
      const stay = document.createElement('button');
      stay.type = 'button';
      stay.className = 'button button-primary';
      stay.textContent = 'Seguir conectado';
      stay.addEventListener('click', () => onActivity());
      banner.append(text, stay);
      document.body.appendChild(banner);
    }
    banner.querySelector('span').textContent =
      `Por seguridad, tu sesión se cerrará en ${seconds} s por inactividad.`;
  };

  const onActivity = () => {
    const now = Date.now();
    lastActivity = now;
    share(now);
    if (banner) { hideBanner(); ping(); }
  };
  ['keydown', 'mousedown', 'mousemove', 'wheel', 'touchstart', 'scroll'].forEach(type =>
    document.addEventListener(type, onActivity, { passive: true, capture: true }));

  setInterval(() => {
    if (closing) return;
    const now = Date.now();
    lastActivity = Math.max(lastActivity, shared());           // otra pestaña pudo estar en uso
    const idle = now - lastActivity;
    if (idle >= limit) {
      closing = true;
      post(expireUrl).finally(() => { window.location.href = loginUrl; });
    } else if (idle >= limit - WARN_BEFORE) {
      showBanner(Math.ceil((limit - idle) / 1000));
    } else {
      hideBanner();
      if (lastActivity > lastPing && now - lastPing >= PING_EVERY) ping();
    }
  }, 1000);
})();
