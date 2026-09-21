/* Administrator views: dashboard, users, audit log, notifications, sessions, reports. */
import {
  S, $, $$, esc, api, bus, debounce, icon, toast, openModal, confirmDialog, download, timeTag, fmtTime, ago,
  avatar, levelBadge, LEVEL, ACTION, actionLabel, feedItem, genPassword, permMatrix, readMatrix, deviceName,
} from './core.js';

const head = (title, sub, actions = '') =>
  `<header class="page-head"><div><h1>${esc(title)}</h1><p>${esc(sub)}</p></div><div class="actions">${actions}</div></header>`;

/* ============================== Dashboard ================================= */
const kpi = (label, ic, value, note, cls = '') =>
  `<div class="card kpi ${cls}"><div class="label">${icon(ic, 16)}${esc(label)}</div><div class="value">${value}</div><div class="note">${note}</div></div>`;

function kpisHtml(s) {
  return kpi('Total users', 'users', s.total_users, `${s.active_users} active, ${s.admins} admin`) +
    kpi('Login count', 'user', s.login_count, `${s.logins_today} today`) +
    kpi('Online now', 'monitor', s.online_now, `${s.live_connections} live connection(s)`) +
    kpi('Failed logins (24 h)', 'alert', s.failed_24h, s.locked ? `${s.locked} account(s) locked` : 'No accounts locked', s.failed_24h ? 'alert' : '');
}

function ring(score) {
  const C = 2 * Math.PI * 42;
  const tone = score >= 90 ? 'ok' : score >= 75 ? 'good' : score >= 50 ? 'warn' : 'danger';
  return `<svg class="ring ring-${tone}" viewBox="0 0 100 100" role="img" aria-label="Security health ${score} out of 100">
    <circle class="ring-bg" cx="50" cy="50" r="42"/><circle class="ring-fg" cx="50" cy="50" r="42" stroke-dasharray="${C.toFixed(1)}" stroke-dashoffset="${(C * (1 - score / 100)).toFixed(1)}" transform="rotate(-90 50 50)"/>
    <text x="50" y="53" text-anchor="middle" class="ring-num">${score}</text><text x="50" y="67" text-anchor="middle" class="ring-sub">of 100</text></svg>`;
}
function healthHtml(h) {
  const ic = { ok: ['check', 's-ok', 'Passed'], warn: ['alert', 's-warn', 'Warning'], fail: ['x-circle', 's-fail', 'Failed'] };
  return `<div class="health">${ring(h.score)}<div><h3>${esc(h.label)}</h3><p class="muted">Based on ${h.checks.length} checks, updated live.</p></div></div>
    <ul class="checks">${h.checks.map((c) => `<li><span class="${ic[c.status][1]}" title="${ic[c.status][2]}">${icon(ic[c.status][0], 16)}</span>
      <div><strong>${esc(c.label)}</strong><small>${esc(c.detail)}</small></div></li>`).join('')}</ul>`;
}
function trendHtml(trend) {
  const W = 460, H = 180, p = { l: 30, r: 8, t: 10, b: 24 };
  const top = Math.max(4, Math.ceil(Math.max(...trend.map((d) => Math.max(d.logins, d.failed))) / 2) * 2);
  const iw = W - p.l - p.r, ih = H - p.t - p.b, gw = iw / trend.length, bw = Math.min(16, gw / 3);
  const y = (v) => p.t + ih - (v / top) * ih;
  let g = '';
  [0, top / 2, top].forEach((t) => { g += `<line class="grid" x1="${p.l}" x2="${W - p.r}" y1="${y(t)}" y2="${y(t)}"/><text x="${p.l - 6}" y="${y(t) + 3}" text-anchor="end">${t}</text>`; });
  trend.forEach((d, i) => {
    const cx = p.l + gw * i + gw / 2;
    g += `<rect class="bar-ok" x="${cx - bw - 1}" y="${y(d.logins)}" width="${bw}" height="${ih - (y(d.logins) - p.t)}" rx="2"><title>${d.logins} logins on ${d.date}</title></rect>
      <rect class="bar-fail" x="${cx + 1}" y="${y(d.failed)}" width="${bw}" height="${ih - (y(d.failed) - p.t)}" rx="2"><title>${d.failed} failed on ${d.date}</title></rect>
      <text x="${cx}" y="${H - 8}" text-anchor="middle">${d.label}</text>`;
  });
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Logins and failed logins over the last 7 days">${g}</svg>
    <div class="legend"><span><i class="bar-ok" style="background:var(--brand)"></i>Successful logins</span><span><i style="background:var(--red)"></i>Failed logins</span></div>`;
}
const noteItem = (n) => `<li class="tone-${n.severity === 'info' ? 'info' : n.severity}"><span class="ico">${icon(n.kind === 'failed_login' ? 'alert' : 'activity', 16)}</span>
  <div><p><strong>${esc(n.title)}</strong>${n.is_read ? '' : ' <span class="badge info plain">New</span>'}</p><p class="sub">${esc(n.message || '')}</p></div>${timeTag(n.ts)}</li>`;

export async function dashboard(root, rid) {
  const [stats, feed, notes] = await Promise.all([
    api('GET', '/api/admin/stats'), api('GET', '/api/admin/activity?type=all&limit=25'), api('GET', '/api/admin/notifications?limit=6')]);
  if (rid !== S.renderId) return;
  const D = { tab: 'all', feed: feed.items, notes: notes.items };
  root.innerHTML = head('Dashboard', 'Live overview of users, sign-ins and security across the plant.') +
    `<div class="kpis" id="kpis">${kpisHtml(stats)}</div>
     <div class="grid-2">
       <section class="card"><div class="card-head"><h2>Activity feed</h2>
         <div class="tabs" role="tablist"><button role="tab" data-tab="all" aria-selected="true">All</button><button role="tab" data-tab="logins" aria-selected="false">Recent logins</button><button role="tab" data-tab="users" aria-selected="false">User changes</button></div></div>
         <ul class="feed" id="feed"></ul></section>
       <section class="card"><div class="card-head"><h2>Security health</h2></div><div id="health">${healthHtml(stats.health)}</div></section>
     </div>
     <div class="grid-2 even">
       <section class="card"><div class="card-head"><h2>Logins, last 7 days</h2></div><div class="card-body" id="trend">${trendHtml(stats.trend)}</div></section>
       <section class="card"><div class="card-head"><h2>Notification center</h2><a class="btn sm" href="#/notifications">View all</a></div><ul class="feed" id="notes"></ul></section>
     </div>`;
  const renderFeed = (freshId) => {
    $('#feed').innerHTML = D.feed.length ? D.feed.map((e) => feedItem(e, e.id === freshId)).join('') : '<li><div><p class="muted">No activity yet.</p></div></li>';
  };
  const renderNotes = () => { $('#notes').innerHTML = D.notes.length ? D.notes.map(noteItem).join('') : '<li><div><p class="muted">No notifications yet.</p></div></li>'; };
  renderFeed(); renderNotes();

  const matches = (e) => D.tab === 'all' || (D.tab === 'logins' && e.category === 'auth') || (D.tab === 'users' && e.category === 'user');
  $$('[data-tab]', root).forEach((b) => b.addEventListener('click', async () => {
    D.tab = b.dataset.tab;
    $$('[data-tab]', root).forEach((x) => x.setAttribute('aria-selected', x === b ? 'true' : 'false'));
    try { D.feed = (await api('GET', `/api/admin/activity?type=${D.tab}&limit=25`)).items; renderFeed(); } catch (e) { toast(e.message, 'error'); }
  }));

  const refresh = debounce(async () => {
    try {
      const s = await api('GET', '/api/admin/stats', undefined, { bg: true });
      if (rid !== S.renderId) return;
      $('#kpis').innerHTML = kpisHtml(s); $('#health').innerHTML = healthHtml(s.health); $('#trend').innerHTML = trendHtml(s.trend);
    } catch { /* ignore transient errors */ }
  }, 600);
  S.cleanups.push(
    bus.on('audit', (e) => { if (matches(e)) { D.feed = [e, ...D.feed].slice(0, 30); renderFeed(e.id); } refresh(); }),
    bus.on('presence', refresh),
    bus.on('notification', (n) => { D.notes = [n, ...D.notes].slice(0, 6); renderNotes(); }));
}

/* ================================= Users ================================== */
const statusCell = (u) => u.locked ? '<span class="badge danger">Locked</span>' : !u.is_active ? '<span class="badge lvl-none">Disabled</span>'
  : u.must_change_password ? '<span class="badge warn">Must change password</span>' : '<span class="badge ok">Active</span>';

function userRow(u) {
  const chips = u.role === 'admin' ? '<span class="chip lvl-edit">All shops: Edit</span>'
    : S.modules.map((m) => `<span class="chip lvl-${u.permissions[m.key]}" title="${esc(m.name)}: ${LEVEL[u.permissions[m.key]]}">${esc(m.name.replace(' Shop', ''))}: ${LEVEL[u.permissions[m.key]]}</span>`).join('');
  const b = (act, ic, label) => `<button class="icon-btn" data-act="${act}" data-id="${u.id}" title="${label}" aria-label="${label} ${esc(u.username)}">${icon(ic)}</button>`;
  const self = u.id === S.me.id;
  return `<tr data-row="${u.id}"><td><div class="who">${avatar(u.full_name)}<div><strong>${esc(u.full_name)}</strong><small>${esc(u.username)}${u.department ? ', ' + esc(u.department) : ''}</small></div></div></td>
    <td><span class="badge ${u.role === 'admin' ? 'info' : 'plain'}">${u.role === 'admin' ? 'Admin' : 'User'}</span></td>
    <td>${statusCell(u)}${u.online ? '<div><small><span class="online-dot"></span>Online</small></div>' : ''}</td>
    <td><div class="chips">${chips}</div></td><td>${u.last_login ? timeTag(u.last_login) : '<span class="muted">Never</span>'}</td>
    <td class="num">${u.login_count}</td>
    <td><div class="row-actions">${u.role === 'user' ? b('perms', 'key', 'Change permissions') : ''}${b('reset', 'lock', 'Reset password')}
      ${u.locked ? b('unlock', 'unlock', 'Unlock account') : ''}${self ? '' : b('toggle', 'power', u.is_active ? 'Disable user' : 'Enable user') + b('delete', 'trash', 'Delete user')}</div></td></tr>`;
}

export async function users(root, rid) {
  let list = (await api('GET', '/api/admin/users')).items;
  if (rid !== S.renderId) return;
  root.innerHTML = head('User management', 'Create users, set access to each shop and manage accounts.',
    `<button class="btn primary" id="new-user">${icon('user-plus')}Create user</button>`) +
    `<div class="card"><div class="table-wrap"><table class="table"><thead><tr><th>User</th><th>Role</th><th>Status</th><th>Shop access</th><th>Last login</th><th class="num">Logins</th><th><span class="sr-only">Actions</span></th></tr></thead><tbody id="users-body"></tbody></table></div></div>`;
  const draw = () => { $('#users-body').innerHTML = list.map(userRow).join(''); };
  const reload = async (bg) => { try { list = (await api('GET', '/api/admin/users', undefined, { bg })).items; if (rid === S.renderId) draw(); } catch { /* ignore */ } };
  draw();
  const debounced = debounce(() => reload(true), 500);
  S.cleanups.push(bus.on('presence', debounced), bus.on('audit', (e) => { if (e.category === 'user' || e.action.startsWith('ACCOUNT') || e.action === 'LOGIN_FAILED') debounced(); }));

  $('#new-user').addEventListener('click', () => userModal(() => reload()));
  $('#users-body').addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-act]'); if (!btn) return;
    const u = list.find((x) => x.id === +btn.dataset.id); if (!u) return;
    try {
      if (btn.dataset.act === 'perms') permsModal(u, () => reload());
      else if (btn.dataset.act === 'reset') resetModal(u, () => reload());
      else if (btn.dataset.act === 'unlock') { await api('POST', `/api/admin/users/${u.id}/unlock`); toast(`${u.username} unlocked.`, 'success'); reload(); }
      else if (btn.dataset.act === 'toggle') {
        if (!u.is_active || await confirmDialog({ title: 'Disable user', message: `Disable <strong>${esc(u.full_name)}</strong>? Their sessions end immediately.`, confirmText: 'Disable', danger: true })) {
          await api('PATCH', `/api/admin/users/${u.id}`, { is_active: !u.is_active }); toast(`${u.username} ${u.is_active ? 'disabled' : 'enabled'}.`, 'success'); reload();
        }
      } else if (btn.dataset.act === 'delete') {
        if (await confirmDialog({ title: 'Delete user', message: `Delete <strong>${esc(u.full_name)}</strong> (${esc(u.username)})? Their sessions end immediately. Audit history is kept.`, confirmText: 'Delete user', danger: true })) {
          await api('DELETE', `/api/admin/users/${u.id}`); toast(`${u.username} deleted.`, 'success'); reload();
        }
      }
    } catch (ex) { toast(ex.message, 'error'); }
  });
}

function passwordField(name = 'password') {
  return `<label class="field full"><span>Temporary password</span><div class="input-row"><input type="text" name="${name}" required autocomplete="off" spellcheck="false"><button type="button" class="btn" data-gen>Generate</button></div>
    <small>Share it securely. The user must choose a new password at first sign-in.</small></label>`;
}
const bindGen = (m, form) => m.$('[data-gen]').addEventListener('click', () => { form.elements.password.value = genPassword(); });

function userModal(done) {
  openModal({
    title: 'Create user', wide: true,
    body: `<form id="cu" class="form-grid" autocomplete="off">
      <label class="field"><span>Full name</span><input type="text" name="full_name" maxlength="80" required></label>
      <label class="field"><span>Username</span><input type="text" name="username" pattern="[A-Za-z0-9._-]{3,32}" title="3-32 letters, numbers, dot, dash or underscore" required autocapitalize="none"></label>
      <label class="field"><span>Email <i>(optional)</i></span><input type="email" name="email"></label>
      <label class="field"><span>Department <i>(optional)</i></span><input type="text" name="department" maxlength="80"></label>
      <label class="field"><span>Role</span><select name="role"><option value="user">User</option><option value="admin">Admin</option></select></label>
      <div></div>${passwordField()}
      <div class="full" id="cu-perms"><h3>Shop access</h3>${permMatrix()}</div>
      <p class="form-error full" id="cu-err" role="alert" hidden></p></form>`,
    footer: '<button class="btn" data-close>Cancel</button><button class="btn primary" type="submit" form="cu">Create user</button>',
    onMount: (m) => {
      const f = m.$('#cu'), err = m.$('#cu-err');
      bindGen(m, f);
      f.elements.role.addEventListener('change', () => { m.$('#cu-perms').hidden = f.elements.role.value === 'admin'; });
      f.addEventListener('submit', async (e) => {
        e.preventDefault(); err.hidden = true;
        try {
          await api('POST', '/api/admin/users', { full_name: f.elements.full_name.value, username: f.elements.username.value, email: f.elements.email.value,
            department: f.elements.department.value, role: f.elements.role.value, password: f.elements.password.value, permissions: readMatrix(f) });
          m.close(); toast('User created.', 'success'); done();
        } catch (ex) { err.textContent = ex.message; err.hidden = false; }
      });
    },
  });
}
function permsModal(u, done) {
  openModal({
    title: `Permissions for ${u.full_name}`,
    body: `<form id="pm">${permMatrix(u.permissions)}<p class="hint" style="margin-top:.75rem">Changes apply immediately, even if the user is signed in.</p><p class="form-error" id="pm-err" role="alert" hidden></p></form>`,
    footer: '<button class="btn" data-close>Cancel</button><button class="btn primary" type="submit" form="pm">Save permissions</button>',
    onMount: (m) => m.$('#pm').addEventListener('submit', async (e) => {
      e.preventDefault();
      try { await api('PUT', `/api/admin/users/${u.id}/permissions`, { permissions: readMatrix(m.el) }); m.close(); toast('Permissions updated.', 'success'); done(); }
      catch (ex) { const b = m.$('#pm-err'); b.textContent = ex.message; b.hidden = false; }
    }),
  });
}
function resetModal(u, done) {
  openModal({
    title: `Reset password for ${u.full_name}`,
    body: `<form id="rp" class="form-grid" autocomplete="off">${passwordField()}<p class="form-error full" id="rp-err" role="alert" hidden></p></form>`,
    footer: '<button class="btn" data-close>Cancel</button><button class="btn primary" type="submit" form="rp">Reset password</button>',
    onMount: (m) => {
      const f = m.$('#rp'); bindGen(m, f);
      f.addEventListener('submit', async (e) => {
        e.preventDefault();
        try { await api('POST', `/api/admin/users/${u.id}/reset-password`, { password: f.elements.password.value }); m.close(); toast('Password reset. The user must change it at next sign-in.', 'success'); done(); }
        catch (ex) { const b = m.$('#rp-err'); b.textContent = ex.message; b.hidden = false; }
      });
    },
  });
}

/* ============================== Audit log ================================= */
export async function audit(root, rid) {
  const F = { page: 1, category: '', action: '', result: '', q: '', from: '', to: '' };
  root.innerHTML = head('Audit log', 'A tamper-evident record of sign-ins, record updates and user actions.',
    `<button class="btn" id="verify">${icon('shield')}Verify integrity</button><button class="btn" data-exp="pdf">${icon('download')}PDF</button><button class="btn" data-exp="xlsx">${icon('download')}Excel</button>`) +
    `<div class="card"><form class="toolbar" id="af">
      <div class="search">${icon('search', 16)}<input type="search" name="q" placeholder="Search user, target, details or IP" aria-label="Search audit log"></div>
      <select name="category" aria-label="Category"><option value="">All categories</option><option value="auth">Sign-in</option><option value="record">Records</option><option value="user">User management</option><option value="security">Security</option><option value="export">Exports</option></select>
      <select name="action" aria-label="Action"><option value="">All actions</option>${Object.keys(ACTION).map((a) => `<option value="${a}">${esc(actionLabel(a))}</option>`).join('')}</select>
      <select name="result" aria-label="Result"><option value="">Any result</option><option value="1">Success</option><option value="0">Failed</option></select>
      <input type="date" name="from" aria-label="From date"><input type="date" name="to" aria-label="To date"></form>
      <div class="table-wrap"><table class="table"><thead><tr><th>Time</th><th>User</th><th>Action</th><th>Target</th><th>Details</th><th>IP</th><th>Result</th></tr></thead><tbody id="audit-body"></tbody></table></div>
      <div class="pager"><span id="pg-info"></span><span><button class="btn sm" id="pg-prev">Previous</button> <button class="btn sm" id="pg-next">Next</button></span></div></div>`;
  let data = null;
  const load = async (bg = false) => {
    const qs = new URLSearchParams({ ...F, per_page: 25 }); [...qs.keys()].forEach((k) => !qs.get(k) && qs.delete(k));
    try {
      data = await api('GET', `/api/admin/audit?${qs}`, undefined, { bg }); if (rid !== S.renderId) return;
      $('#audit-body').innerHTML = data.items.length ? data.items.map((e) => `<tr><td title="${esc(fmtTime(e.ts))}">${esc(new Date(e.ts).toLocaleString())}</td><td>${esc(e.username || '-')}</td>
        <td>${esc(actionLabel(e.action))}</td><td class="wrap">${esc(e.target || '')}</td><td class="wrap">${esc(e.details || '')}</td><td>${esc(e.ip || '')}</td>
        <td>${e.success ? '<span class="badge ok">Success</span>' : '<span class="badge danger">Failed</span>'}</td></tr>`).join('')
        : '<tr><td colspan="7"><div class="empty">No entries match these filters.</div></td></tr>';
      $('#pg-info').textContent = `Page ${data.page} of ${data.pages} (${data.total} entries)`;
      $('#pg-prev').disabled = data.page <= 1; $('#pg-next').disabled = data.page >= data.pages;
    } catch (e) { if (!bg) toast(e.message, 'error'); }
  };
  const onFilter = debounce(() => { const f = $('#af').elements; Object.keys(F).forEach((k) => { if (k !== 'page' && f[k]) F[k] = f[k].value; }); F.page = 1; load(); }, 300);
  $('#af').addEventListener('input', onFilter); $('#af').addEventListener('submit', (e) => e.preventDefault());
  $('#pg-prev').addEventListener('click', () => { F.page--; load(); });
  $('#pg-next').addEventListener('click', () => { F.page++; load(); });
  $$('[data-exp]', root).forEach((b) => b.addEventListener('click', () => download(`/api/admin/export/audit?fmt=${b.dataset.exp}`)));
  $('#verify').addEventListener('click', async () => {
    try { const r = await api('GET', '/api/admin/audit/verify'); r.ok ? toast(`Audit trail intact: ${r.checked} entries verified.`, 'success') : toast(`Tampering detected at entry #${r.broken_at}.`, 'error', 10000); }
    catch (e) { toast(e.message, 'error'); }
  });
  await load();
  const live = debounce(() => { if (F.page === 1) load(true); }, 700);
  S.cleanups.push(bus.on('audit', live));
}

/* ============================ Notifications =============================== */
export async function notifications(root, rid) {
  let kind = '', items = [];
  root.innerHTML = head('Notification center', 'Latest user activity and failed login alerts.', '<button class="btn" id="mark">Mark all as read</button>') +
    `<div class="card"><div class="card-head"><div class="tabs" role="tablist"><button role="tab" data-k="" aria-selected="true">All</button><button role="tab" data-k="user_activity" aria-selected="false">Latest user activity</button><button role="tab" data-k="failed_login" aria-selected="false">Failed logins</button></div></div><ul class="feed" id="nl" style="max-height:none"></ul></div>`;
  const draw = () => { $('#nl').innerHTML = items.length ? items.map(noteItem).join('') : '<li><div><p class="muted">Nothing here yet.</p></div></li>'; };
  const load = async (bg) => { const r = await api('GET', `/api/admin/notifications?kind=${kind}&limit=100`, undefined, { bg }); if (rid === S.renderId) { items = r.items; S.setUnread(r.unread); draw(); } };
  await load(false);
  $$('[data-k]', root).forEach((b) => b.addEventListener('click', async () => {
    kind = b.dataset.k; $$('[data-k]', root).forEach((x) => x.setAttribute('aria-selected', x === b ? 'true' : 'false')); await load(false);
  }));
  $('#mark').addEventListener('click', async () => { const r = await api('POST', '/api/admin/notifications/read', {}); S.setUnread(r.unread); items.forEach((n) => { n.is_read = 1; }); draw(); });
  S.cleanups.push(bus.on('notification', (n) => { if (!kind || n.kind === kind) { items = [n, ...items]; draw(); } }));
}

/* =============================== Sessions ================================= */
export async function sessions(root, rid) {
  root.innerHTML = head('Active sessions', 'Everyone currently signed in. End a session to sign that person out immediately.') +
    '<div class="card"><div class="table-wrap"><table class="table"><thead><tr><th>User</th><th>Role</th><th>Device</th><th>IP</th><th>Signed in</th><th>Last active</th><th></th></tr></thead><tbody id="sb"></tbody></table></div></div>';
  const load = async (bg) => {
    const r = await api('GET', '/api/admin/sessions', undefined, { bg }); if (rid !== S.renderId) return;
    $('#sb').innerHTML = r.items.length ? r.items.map((s) => `<tr><td><div class="who">${avatar(s.full_name)}<div><strong>${esc(s.full_name)}</strong><small>${esc(s.username)}</small></div></div></td>
      <td>${s.role === 'admin' ? 'Admin' : 'User'}</td><td>${esc(deviceName(s.user_agent))}</td><td>${esc(s.ip || '')}</td><td>${timeTag(s.created_at)}</td><td>${timeTag(s.last_seen)}</td>
      <td class="num">${s.current ? '<span class="badge info plain">This session</span>' : `<button class="btn sm" data-end="${s.id}">End session</button>`}</td></tr>`).join('')
      : '<tr><td colspan="7"><div class="empty">No active sessions.</div></td></tr>';
  };
  await load(false);
  $('#sb').addEventListener('click', async (e) => {
    const b = e.target.closest('[data-end]'); if (!b) return;
    try { await api('DELETE', `/api/admin/sessions/${b.dataset.end}`); toast('Session ended.', 'success'); load(false); } catch (ex) { toast(ex.message, 'error'); }
  });
  S.cleanups.push(bus.on('presence', debounce(() => load(true), 400)));
}

/* ================================ Reports ================================= */
export async function reports(root) {
  const R = [
    ['audit', 'Audit trail', 'Every sign-in, record change, user action and export (latest 10,000 entries).', 'file'],
    ['logins', 'Login activity', 'Sign-ins, sign-outs, failed attempts, lockouts and session timeouts.', 'user'],
    ['users', 'User and permission register', 'All users with role, status, last login and access level for each shop.', 'users'],
    ['records', 'Shop records', 'Records from all four shops in a single workbook or document.', 'box'],
  ];
  root.innerHTML = head('Export reports', 'Download reports as PDF or Excel. Each export is recorded in the audit log.') +
    `<div class="tiles">${R.map(([k, t, d, ic]) => `<div class="card tile"><div class="icon-wrap">${icon(ic)}</div><h2>${esc(t)}</h2><p>${esc(d)}</p>
      <div class="btns"><button class="btn" data-r="${k}" data-f="pdf">${icon('download', 16)}PDF</button><button class="btn" data-r="${k}" data-f="xlsx">${icon('download', 16)}Excel</button></div></div>`).join('')}</div>`;
  const onClick = (e) => { const b = e.target.closest('[data-r]'); if (b) download(`/api/admin/export/${b.dataset.r}?fmt=${b.dataset.f}`); };
  root.addEventListener('click', onClick);
  S.cleanups.push(() => root.removeEventListener('click', onClick));
}
