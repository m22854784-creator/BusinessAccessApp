/* Application shell: navigation, routing, live stream (SSE) and session timeout. */
import {
  S, $, $$, esc, api, bus, icon, toast, openModal, themeToggleHtml, avatar, LEVEL, ago, errorState,
  passwordFormHtml, bindPasswordForm,
} from './core.js';
import * as adminViews from './views-admin.js';
import * as userViews from './views-user.js';

const isAdmin = () => S.me.role === 'admin';
let es = null, redirecting = false;

/* ---- sign-out helpers --------------------------------------------------- */
function goLogin(code) {
  if (redirecting) return; redirecting = true;
  const reason = { SESSION_TIMEOUT: 'timeout', timeout: 'timeout', SESSION_TERMINATED: 'terminated', terminated: 'terminated' }[code];
  location.href = '/login' + (reason ? `?reason=${reason}` : '');
}
async function signOut() {
  try { await api('POST', '/api/logout'); } catch { /* already signed out */ }
  goLogin();
}

/* ---- data from /api/me -------------------------------------------------- */
function applyMe(d) {
  S.me = d.user; S.perms = d.permissions; S.modules = d.modules; S.statuses = d.statuses;
  S.idleLimit = d.idle_timeout; S.deadline = Date.now() + d.remaining * 1000; S.setUnread(d.unread || 0);
}
S.setUnread = (n) => {
  S.unread = Math.max(0, n);
  const c = $('#bell-count'); if (c) { c.textContent = S.unread > 99 ? '99+' : S.unread; c.hidden = !S.unread; }
  const nb = $('[data-nav-badge="notifications"]'); if (nb) { nb.textContent = S.unread; nb.hidden = !S.unread; }
};

/* ---- shell -------------------------------------------------------------- */
function buildShell() {
  $('#app').innerHTML = `<div class="shell" id="shell">
    <aside class="sidebar"><a class="brand" href="#/"><span class="wordmark">godrej</span><small>Access management</small></a>
      <nav id="nav" aria-label="Main navigation"></nav>
      <div class="side-foot"><div class="me">${avatar(S.me.full_name)}<div style="min-width:0"><strong>${esc(S.me.full_name)}</strong><small>${isAdmin() ? 'Administrator' : 'User'}</small></div></div>
        <button class="btn" id="signout">${icon('logout')}Sign out</button></div></aside>
    <div class="main"><header class="topbar"><button class="icon-btn only-mobile" id="menu" aria-label="Open menu">${icon('menu')}</button>
      <span class="crumb">Godrej &amp; Boyce, Business Access Management</span>
      <span class="live" id="live" role="status"><i></i><span>Connecting</span></span>
      ${isAdmin() ? `<a class="icon-btn" href="#/notifications" aria-label="Notifications" title="Notifications">${icon('bell')}<span class="bell-count" id="bell-count" hidden></span></a>` : ''}
      ${themeToggleHtml()}</header><main id="view" tabindex="-1"></main></div></div>`;
  $('#signout').addEventListener('click', signOut);
  $('#menu').addEventListener('click', () => $('#shell').classList.toggle('open'));
  $('#nav').addEventListener('click', () => $('#shell').classList.remove('open'));
  renderNav(); S.setUnread(S.unread);
}
function renderNav() {
  const link = (id, label, ic, extra = '') => `<a class="nav-link" href="#/${id}" data-nav="${id}">${icon(ic)}<span class="grow">${esc(label)}</span>${extra}</a>`;
  let h = link(isAdmin() ? 'dashboard' : 'home', isAdmin() ? 'Dashboard' : 'My workspace', 'grid');
  h += '<div class="nav-group">Shops</div>';
  h += S.modules.filter((m) => S.perms[m.key] !== 'none').map((m) =>
    link(`module/${m.key}`, m.name, m.icon, isAdmin() ? '' : `<span class="nav-level">${LEVEL[S.perms[m.key]]}</span>`)).join('') ||
    '<p class="nav-group">No shops assigned yet</p>';
  if (isAdmin()) {
    h += '<div class="nav-group">Administration</div>' + link('users', 'User management', 'users') + link('audit', 'Audit log', 'file') +
      link('notifications', 'Notifications', 'bell', '<span class="nav-badge" data-nav-badge="notifications" hidden></span>') +
      link('sessions', 'Active sessions', 'monitor') + link('reports', 'Export reports', 'download');
  }
  h += '<div class="nav-group">Account</div>' + link('account', 'My account', 'user');
  $('#nav').innerHTML = h; S.setUnread(S.unread); markNav();
}
const markNav = () => $$('.nav-link').forEach((a) => {
  const on = location.hash.replace(/^#\//, '') === a.dataset.nav; on ? a.setAttribute('aria-current', 'page') : a.removeAttribute('aria-current');
});

/* ---- router ------------------------------------------------------------- */
const ADMIN_VIEWS = { dashboard: adminViews.dashboard, users: adminViews.users, audit: adminViews.audit,
  notifications: adminViews.notifications, sessions: adminViews.sessions, reports: adminViews.reports };
async function route() {
  S.cleanups.forEach((fn) => fn()); S.cleanups = [];
  const rid = ++S.renderId, root = $('#view');
  let [name, arg] = location.hash.replace(/^#\/?/, '').split('/');
  if (!name || (name === 'home' && isAdmin()) || (name === 'dashboard' && !isAdmin())) { name = isAdmin() ? 'dashboard' : 'home'; history.replaceState(null, '', `#/${name}`); }
  markNav();
  root.innerHTML = '<div class="loading">Loading...</div>';
  try {
    if (ADMIN_VIEWS[name]) {
      if (!isAdmin()) { root.innerHTML = '<div class="empty"><h3>Administrators only</h3><p>This area is not available for your account.</p></div>'; return; }
      await ADMIN_VIEWS[name](root, rid);
    } else if (name === 'module') await userViews.moduleView(root, rid, arg);
    else if (name === 'account') await userViews.account(root, rid);
    else await userViews.home(root, rid);
  } catch (e) { if (rid === S.renderId && e.data?.code !== 'PASSWORD_CHANGE_REQUIRED') root.innerHTML = errorState(e.message); }
  if (rid === S.renderId) root.focus({ preventScroll: true });
}

/* ---- live stream (Server-Sent Events) ------------------------------------ */
function setLive(on) { const el = $('#live'); if (el) { el.classList.toggle('on', on); $('span', el).textContent = on ? 'Live' : 'Reconnecting'; } }
function connectStream() {
  es?.close(); es = new EventSource('/api/stream');
  es.addEventListener('hello', () => { setLive(true); bus.emit('reconnected'); });
  es.onerror = async () => {
    setLive(false);
    if (es.readyState === EventSource.CLOSED) {           // server refused: session may be gone
      try { await api('GET', '/api/session/status', undefined, { bg: true }); setTimeout(connectStream, 3000); } catch { /* 401 redirects */ }
    }
  };
  const on = (name, fn) => es.addEventListener(name, (e) => fn(JSON.parse(e.data)));
  on('audit', (d) => bus.emit('audit', d));
  on('presence', (d) => bus.emit('presence', d));
  on('record', (d) => bus.emit('record', d));
  on('notification', (n) => {
    S.setUnread(S.unread + 1); bus.emit('notification', n);
    if (n.severity !== 'info') toast(`${n.title}: ${n.message || ''}`, n.severity === 'danger' ? 'error' : 'warn', 7000);
  });
  on('permissions', async () => {
    try { applyMe(await api('GET', '/api/me', undefined, { bg: true })); renderNav(); toast('An administrator changed your access.', 'info', 6000); route(); } catch { /* ignore */ }
  });
  on('force_logout', (d) => { es.close(); goLogin(d.reason); });
}

/* ---- idle timeout: warn at 60 s, sign out at 0 --------------------------- */
let warn = null, lastPing = 0, checking = false;
function startIdle() {
  const activity = () => {
    if (warn || Date.now() - lastPing < 30000) return;
    lastPing = Date.now(); S.deadline = Date.now() + S.idleLimit * 1000;
    api('POST', '/api/session/ping').catch(() => {});
  };
  ['mousemove', 'keydown', 'click', 'touchstart', 'scroll'].forEach((ev) => window.addEventListener(ev, activity, { passive: true }));
  setInterval(async () => {
    const left = Math.round((S.deadline - Date.now()) / 1000);
    if (warn) {
      $('#idle-count', warn.el).textContent = `${Math.max(0, left)} s`;
      if (left <= 0) { warn.close(); warn = null; checkServer(); }
    } else if (left <= 60 && !checking) {
      checking = true;
      const st = await checkServer(); checking = false;                       // another tab may have kept us alive
      if (st && st.remaining > 60) { S.deadline = Date.now() + st.remaining * 1000; return; }
      if (st && !warn) showWarn();
    }
  }, 1000);
  setInterval(() => $$('time[data-ts]').forEach((t) => { t.textContent = ago(t.dataset.ts); }), 30000);
}
async function checkServer() {
  try { const st = await api('GET', '/api/session/status', undefined, { bg: true }); S.deadline = Date.now() + st.remaining * 1000; return st; } catch { return null; }
}
function showWarn() {
  warn = openModal({ title: 'Still there?', dismissible: false,
    body: `<p>For security, you will be signed out soon because of inactivity.</p><div class="countdown" id="idle-count" aria-live="off">60 s</div>`,
    footer: `<button class="btn" id="idle-out">Sign out</button><button class="btn primary" id="idle-stay">Stay signed in</button>`,
    onMount: (m) => {
      m.$('#idle-out').addEventListener('click', signOut);
      m.$('#idle-stay').addEventListener('click', async () => { m.close(); warn = null; lastPing = Date.now(); try { await api('POST', '/api/session/ping'); } catch { /* redirect handled */ } });
    } });
}

/* ---- forced password change --------------------------------------------- */
let pwModal = null;
function forcePasswordChange() {
  if (pwModal) return;
  pwModal = openModal({ title: 'Choose a new password', dismissible: false,
    body: `<p class="muted">Your account uses a temporary password. Set your own before continuing.</p>${passwordFormHtml('pw-force')}`,
    footer: `<button class="btn" id="pw-out">Sign out</button><button class="btn primary" type="submit" form="pw-force">Save password</button>`,
    onMount: (m) => {
      m.$('#pw-out').addEventListener('click', signOut);
      bindPasswordForm(m.$('#pw-force'), async () => {
        m.close(); pwModal = null; S.me.must_change_password = 0; toast('Password saved.', 'success');
        try { applyMe(await api('GET', '/api/me')); renderNav(); } catch { /* ignore */ }
        route();
      });
    } });
}

/* ---- boot --------------------------------------------------------------- */
async function boot() {
  S.csrf = $('meta[name="csrf-token"]').content;
  S.hooks = { unauthorized: goLogin, pwChange: forcePasswordChange };
  try { applyMe(await api('GET', '/api/me', undefined, { bg: true })); } catch { return; }
  buildShell();
  window.addEventListener('hashchange', route);
  let first = true;
  bus.on('reconnected', () => { if (first) { first = false; return; } route(); });   // refresh after a dropped connection
  connectStream(); startIdle();
  if (S.me.must_change_password) forcePasswordChange();   // views load after the password is set
  else await route();
}
boot();
