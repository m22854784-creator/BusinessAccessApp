/* Shared helpers: state, API client, icons, toasts, modals, formatting. */
export const S = {
  csrf: '', me: null, perms: {}, modules: [], statuses: [], unread: 0,
  idleLimit: 900, deadline: 0, renderId: 0, cleanups: [], hooks: {},
};
export const $ = (sel, el = document) => el.querySelector(sel);
export const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
export const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
export const debounce = (fn, ms = 300) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

/* ---- tiny event bus (views subscribe to live events) -------------------- */
const listeners = {};
export const bus = {
  on(evt, fn) { (listeners[evt] ||= []).push(fn); return () => { listeners[evt] = listeners[evt].filter((f) => f !== fn); }; },
  emit(evt, data) { (listeners[evt] || []).slice().forEach((fn) => { try { fn(data); } catch (e) { console.error(e); } }); },
};

/* ---- icons (Feather-style paths) ---------------------------------------- */
const ICONS = {
  grid: '<rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/>',
  users: '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
  user: '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
  'user-plus': '<path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="8.5" cy="7" r="4"/><line x1="20" y1="8" x2="20" y2="14"/><line x1="23" y1="11" x2="17" y2="11"/>',
  bell: '<path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/>',
  shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
  file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/>',
  activity: '<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>',
  logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>',
  monitor: '<rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/>',
  tool: '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>',
  layers: '<polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/>',
  box: '<path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/>',
  zap: '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>',
  trash: '<polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/>',
  edit: '<path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>',
  key: '<path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/>',
  lock: '<rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
  unlock: '<rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 9.9-1"/>',
  power: '<path d="M18.36 6.64a9 9 0 1 1-12.73 0"/><line x1="12" y1="2" x2="12" y2="12"/>',
  plus: '<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>',
  menu: '<line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="18" x2="21" y2="18"/>',
  x: '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>',
  check: '<polyline points="20 6 9 17 4 12"/>',
  alert: '<path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
  'x-circle': '<circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/>',
  search: '<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>',
  clock: '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
  moon: '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>',
  sun: '<circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>',
};
export const icon = (name, size = 18) =>
  `<svg class="icon" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name] || ''}</svg>`;

export const themeToggleHtml = () =>
  `<button class="icon-btn" type="button" data-theme-toggle aria-label="Switch between light and dark mode" title="Light / dark mode"><span class="i-moon">${icon('moon')}</span><span class="i-sun">${icon('sun')}</span></button>`;

/* ---- permission labels -------------------------------------------------- */
export const LEVEL = { none: 'No Access', view: 'View', edit: 'Edit' };
export const levelBadge = (l) => `<span class="badge lvl-${l}">${LEVEL[l]}</span>`;

/* ---- API client --------------------------------------------------------- */
export class ApiError extends Error {
  constructor(message, status, data) { super(message); this.status = status; this.data = data; }
}
export async function api(method, url, body, opts = {}) {
  const headers = { 'X-CSRF-Token': S.csrf };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (opts.bg) headers['X-Background'] = '1';   // live refreshes must not extend the session
  let res;
  try {
    res = await fetch(url, { method, headers, credentials: 'same-origin', body: body !== undefined ? JSON.stringify(body) : undefined });
  } catch { throw new ApiError('Cannot reach the server. Check your connection.', 0); }
  let data = null;
  try { data = await res.json(); } catch { /* empty body */ }
  if (res.ok) {
    if (!opts.bg) S.deadline = Date.now() + S.idleLimit * 1000;
    return data;
  }
  if (res.status === 401) S.hooks.unauthorized?.(data?.code);
  if (data?.code === 'PASSWORD_CHANGE_REQUIRED') S.hooks.pwChange?.();
  if (data?.code === 'CSRF') location.reload();
  throw new ApiError(data?.error || 'Request failed.', res.status, data);
}

export async function download(url) {
  try {
    const res = await fetch(url, { credentials: 'same-origin' });
    if (!res.ok) {
      let msg = 'Download failed.';
      try { msg = (await res.json()).error || msg; } catch { /* ignore */ }
      if (res.status === 401) S.hooks.unauthorized?.();
      throw new Error(msg);
    }
    const blob = await res.blob();
    const m = /filename="?([^";]+)"?/.exec(res.headers.get('Content-Disposition') || '');
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob); a.download = m ? m[1] : 'report';
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 4000);
    S.deadline = Date.now() + S.idleLimit * 1000;
    toast('Report downloaded.', 'success');
  } catch (e) { toast(e.message, 'error'); }
}

/* ---- toasts ------------------------------------------------------------- */
export function toast(message, type = 'info', ms = 5000) {
  const box = $('#toasts'); if (!box) return;
  const el = document.createElement('div');
  el.className = `toast toast-${type}`;
  el.innerHTML = `${icon(type === 'error' ? 'alert' : type === 'success' ? 'check' : type === 'warn' ? 'alert' : 'bell')}<span>${esc(message)}</span>`;
  box.append(el);
  setTimeout(() => { el.classList.add('out'); setTimeout(() => el.remove(), 260); }, ms);
}

/* ---- modal -------------------------------------------------------------- */
export function openModal({ title, body, footer = '', wide = false, dismissible = true, onMount }) {
  const prev = document.activeElement;
  const wrap = document.createElement('div');
  wrap.className = 'modal-backdrop';
  wrap.innerHTML = `<div class="modal ${wide ? 'wide' : ''}" role="dialog" aria-modal="true" aria-label="${esc(title)}">
    <header class="modal-head"><h2>${esc(title)}</h2>${dismissible ? `<button class="icon-btn" data-close aria-label="Close">${icon('x')}</button>` : ''}</header>
    <div class="modal-body">${body}</div>${footer ? `<footer class="modal-foot">${footer}</footer>` : ''}</div>`;
  document.body.append(wrap);
  const onKey = (e) => { if (e.key === 'Escape' && dismissible) handle.close(); };
  const handle = {
    el: wrap, $: (s) => $(s, wrap),
    close() { wrap.remove(); document.removeEventListener('keydown', onKey); prev?.focus?.(); handle.onClose?.(); },
  };
  document.addEventListener('keydown', onKey);
  wrap.addEventListener('mousedown', (e) => { if (dismissible && e.target === wrap) handle.close(); });
  wrap.addEventListener('click', (e) => { if (e.target.closest('[data-close]')) handle.close(); });
  onMount?.(handle);
  $('input:not([type=hidden]):not([type=radio]), select, textarea', wrap)?.focus();
  return handle;
}

export function confirmDialog({ title, message, confirmText = 'Confirm', danger = false }) {
  return new Promise((resolve) => {
    let done = false;
    const finish = (v) => { if (!done) { done = true; resolve(v); } };
    const m = openModal({
      title, body: `<p>${message}</p>`,
      footer: `<button class="btn" data-close>Cancel</button><button class="btn ${danger ? 'danger' : 'primary'}" id="cf-ok">${esc(confirmText)}</button>`,
      onMount: (h) => h.$('#cf-ok').addEventListener('click', () => { finish(true); h.close(); }),
    });
    m.onClose = () => finish(false);
  });
}

/* ---- formatting --------------------------------------------------------- */
export const fmtTime = (iso) => iso ? new Date(iso).toLocaleString(undefined,
  { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }) : 'Never';
export function ago(iso) {
  if (!iso) return 'Never';
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 10) return 'just now';
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return fmtTime(iso);
}
export const timeTag = (iso) => `<time data-ts="${esc(iso)}" title="${esc(fmtTime(iso))}">${esc(ago(iso))}</time>`;
export const initials = (name) => (name || '?').split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join('');
export const avatar = (name) => `<span class="avatar" aria-hidden="true">${esc(initials(name))}</span>`;
export const statusBadge = (s) => `<span class="badge status-${esc(s.toLowerCase().replace(/\s+/g, '-'))}">${esc(s)}</span>`;

/* ---- audit action vocabulary (label, feed phrase, tone, icon) ----------- */
export const ACTION = {
  LOGIN: ['Login', 'signed in', 'ok', 'user'],
  LOGOUT: ['Logout', 'signed out', '', 'logout'],
  LOGIN_FAILED: ['Failed login', 'failed to sign in', 'warn', 'alert'],
  LOGIN_BLOCKED: ['Login blocked', 'was blocked from signing in', 'warn', 'lock'],
  ACCOUNT_LOCKED: ['Account locked', 'was locked out', 'danger', 'lock'],
  ACCOUNT_UNLOCKED: ['Account unlocked', 'unlocked account', 'info', 'unlock'],
  SESSION_TIMEOUT: ['Session timeout', 'was signed out after inactivity', '', 'clock'],
  SESSION_TERMINATED: ['Session ended', 'ended a session for', 'info', 'power'],
  USER_CREATED: ['User created', 'created user', 'info', 'user-plus'],
  USER_UPDATED: ['User updated', 'updated user', 'info', 'edit'],
  USER_DELETED: ['User deleted', 'deleted user', 'warn', 'trash'],
  USER_DISABLED: ['User disabled', 'disabled user', 'warn', 'power'],
  USER_ENABLED: ['User enabled', 'enabled user', 'info', 'power'],
  PERMISSIONS_CHANGED: ['Permissions changed', 'changed permissions for', 'info', 'key'],
  PASSWORD_RESET: ['Password reset', 'reset the password of', 'info', 'key'],
  PASSWORD_CHANGED: ['Password changed', 'changed their password', 'info', 'key'],
  PASSWORD_CHANGE_FAILED: ['Password change failed', 'failed to change their password', 'warn', 'alert'],
  RECORD_CREATED: ['Record created', 'added record', 'info', 'plus'],
  RECORD_UPDATED: ['Record updated', 'updated record', 'info', 'edit'],
  RECORD_DELETED: ['Record deleted', 'deleted record', 'warn', 'trash'],
  ACCESS_DENIED: ['Access denied', 'was denied access to', 'warn', 'shield'],
  REPORT_EXPORTED: ['Report exported', 'exported', '', 'download'],
  AUDIT_VERIFIED: ['Audit verified', 'verified the audit trail', 'ok', 'shield'],
  RATE_LIMITED: ['Rate limited', 'was rate limited', 'danger', 'shield'],
  SYSTEM_INIT: ['System started', 'initialised the system', '', 'shield'],
  DEMO_DATA_LOADED: ['Demo data', 'loaded demo data', '', 'file'],
};
export const actionLabel = (a) => ACTION[a]?.[0] || a;

export function feedItem(e, fresh = false) {
  const [, phrase, tone, ico] = ACTION[e.action] || [e.action, e.action.toLowerCase(), '', 'activity'];
  const who = e.username || 'Unknown';
  const t = tone === '' ? '' : `tone-${tone}`;
  const target = e.target ? ` <em>${esc(e.target)}</em>` : '';
  const sub = e.details ? `<p class="sub">${esc(e.details)}${e.ip && e.ip !== 'system' ? ` (from ${esc(e.ip)})` : ''}</p>` : '';
  return `<li class="${t} ${fresh ? 'fresh' : ''}"><span class="ico">${icon(ico, 16)}</span>
    <div><p><strong>${esc(who)}</strong> ${esc(phrase)}${target}</p>${sub}</div>${timeTag(e.ts)}</li>`;
}

/* ---- passwords ---------------------------------------------------------- */
export const PW_RULES = [
  ['At least 8 characters', (p) => p.length >= 8], ['Uppercase letter', (p) => /[A-Z]/.test(p)],
  ['Lowercase letter', (p) => /[a-z]/.test(p)], ['A number', (p) => /\d/.test(p)],
  ['A special character', (p) => /[^A-Za-z0-9]/.test(p)],
];
export const pwRulesHtml = () => `<ul class="pw-rules">${PW_RULES.map(([t]) => `<li>${t}</li>`).join('')}</ul>`;
export function bindPwRules(input, list) {
  const update = () => PW_RULES.forEach(([, fn], i) => list.children[i].classList.toggle('ok', fn(input.value)));
  input.addEventListener('input', update); update();
}
export function genPassword(len = 12) {
  const sets = ['ABCDEFGHJKLMNPQRSTUVWXYZ', 'abcdefghijkmnpqrstuvwxyz', '23456789', '!@#$%&*?'];
  const all = sets.join('');
  const rnd = (n) => { const a = new Uint32Array(1); crypto.getRandomValues(a); return a[0] % n; };
  const out = sets.map((s) => s[rnd(s.length)]);
  while (out.length < len) out.push(all[rnd(all.length)]);
  for (let i = out.length - 1; i > 0; i--) { const j = rnd(i + 1); [out[i], out[j]] = [out[j], out[i]]; }
  return out.join('');
}

/* Change-password form used by the forced modal and the Account page. */
export const passwordFormHtml = (id) => `<form id="${id}" class="form-grid" autocomplete="off">
  <label class="field full"><span>Current password</span><input type="password" name="current" autocomplete="current-password" required></label>
  <label class="field"><span>New password</span><input type="password" name="next" autocomplete="new-password" required></label>
  <label class="field"><span>Confirm new password</span><input type="password" name="confirm" autocomplete="new-password" required></label>
  <div class="full">${pwRulesHtml()}</div>
  <p class="form-error full" role="alert" hidden></p></form>`;
export function bindPasswordForm(form, onSuccess) {
  const err = $('.form-error', form);
  bindPwRules(form.elements.next, $('.pw-rules', form));
  form.addEventListener('submit', async (e) => {
    e.preventDefault(); err.hidden = true;
    if (form.elements.next.value !== form.elements.confirm.value) { err.textContent = 'The new passwords do not match.'; err.hidden = false; return; }
    try {
      await api('POST', '/api/change-password', { current_password: form.elements.current.value, new_password: form.elements.next.value });
      form.reset(); onSuccess?.();
    } catch (ex) { err.textContent = ex.message; err.hidden = false; }
  });
}

/* ---- permission matrix (View / Edit / No Access per shop) ---------------- */
export function permMatrix(values = {}) {
  return `<div class="matrix">${S.modules.map((m) => `<div class="matrix-row">
    <div class="matrix-label">${icon(m.icon)}<span>${esc(m.name)}</span></div>
    <div class="seg" role="radiogroup" aria-label="${esc(m.name)} access">${['none', 'view', 'edit'].map((l) =>
      `<label class="seg-opt lvl-${l}"><input type="radio" name="perm-${m.key}" value="${l}" ${(values[m.key] || 'none') === l ? 'checked' : ''}><span>${LEVEL[l]}</span></label>`).join('')}
    </div></div>`).join('')}</div>`;
}
export const readMatrix = (root) => Object.fromEntries(S.modules.map((m) =>
  [m.key, $(`input[name="perm-${m.key}"]:checked`, root)?.value || 'none']));

export function deviceName(ua = '') {
  const b = /Edg\//.test(ua) ? 'Edge' : /Chrome\//.test(ua) ? 'Chrome' : /Firefox\//.test(ua) ? 'Firefox' : /Safari\//.test(ua) ? 'Safari' : 'Browser';
  const o = /Windows/.test(ua) ? 'Windows' : /Android/.test(ua) ? 'Android' : /iPhone|iPad/.test(ua) ? 'iOS' : /Mac OS/.test(ua) ? 'macOS' : /Linux/.test(ua) ? 'Linux' : '';
  return o ? `${b} on ${o}` : b;
}
export const errorState = (msg) => `<div class="empty"><h3>Could not load this page</h3><p>${esc(msg)}</p></div>`;
