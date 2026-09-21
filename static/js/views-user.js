/* Views for every signed-in person: workspace home, shop modules, account. */
import {
  S, $, $$, esc, api, bus, debounce, icon, toast, openModal, confirmDialog, download, timeTag,
  levelBadge, LEVEL, statusBadge, feedItem, fmtTime, passwordFormHtml, bindPasswordForm,
} from './core.js';

const head = (title, sub, actions = '') =>
  `<header class="page-head"><div><h1>${esc(title)}</h1><p>${esc(sub)}</p></div><div class="actions">${actions}</div></header>`;

/* ============================ Workspace home ============================== */
export async function home(root, rid) {
  const act = await api('GET', '/api/me/activity'); if (rid !== S.renderId) return;
  const h = new Date().getHours();
  const greet = h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening';
  const tiles = S.modules.map((m) => {
    const l = S.perms[m.key];
    const inner = `<div class="icon-wrap">${icon(l === 'none' ? 'lock' : m.icon)}</div><h2>${esc(m.name)}</h2><p>${esc(m.description)}</p><div class="foot">${levelBadge(l)}</div>`;
    return l === 'none' ? `<div class="card tile locked" aria-label="${esc(m.name)}, no access">${inner}</div>`
      : `<a class="card tile" href="#/module/${m.key}">${inner}</a>`;
  }).join('');
  root.innerHTML = head(`${greet}, ${S.me.full_name.split(' ')[0]}`, 'Your shops and what you can do in each one.') +
    `<div class="tiles" id="tiles">${tiles}</div>
     <section class="card" style="margin-top:1.25rem"><div class="card-head"><h2>Your recent activity</h2></div><ul class="feed" id="mine"></ul></section>`;
  $('#mine').innerHTML = act.items.length ? act.items.map((e) => feedItem({ ...e, username: 'You' })).join('') : '<li><div><p class="muted">No activity yet.</p></div></li>';
}

/* ============================== Shop module =============================== */
export async function moduleView(root, rid, key) {
  const mod = S.modules.find((m) => m.key === key);
  if (!mod) { root.innerHTML = '<div class="empty"><h3>Unknown module</h3></div>'; return; }
  if (S.perms[key] === 'none') {
    root.innerHTML = `<div class="empty">${icon('lock', 32)}<h3>No Access to ${esc(mod.name)}</h3><p>Ask an administrator if you need View or Edit access.</p></div>`; return;
  }
  const F = { q: '', status: '' };
  let items = [], level = S.perms[key], flashIds = new Set();
  const canEdit = () => level === 'edit';

  root.innerHTML = head(mod.name, mod.description,
    `${levelBadge(level)}<button class="btn" data-exp="pdf">${icon('download')}PDF</button><button class="btn" data-exp="xlsx">${icon('download')}Excel</button>`) +
    `<div class="card"><div class="toolbar"><div class="search">${icon('search', 16)}<input type="search" id="q" placeholder="Search part number, description or notes" aria-label="Search records"></div>
      <select id="st" aria-label="Filter by status"><option value="">All statuses</option>${S.statuses.map((s) => `<option>${esc(s)}</option>`).join('')}</select>
      <span id="add-slot"></span></div>
      <div id="view-note"></div>
      <div class="table-wrap"><table class="table"><thead><tr><th>Part no.</th><th>Description</th><th class="num">Qty</th><th>Status</th><th>Last updated</th><th><span class="sr-only">Actions</span></th></tr></thead><tbody id="rb"></tbody></table></div></div>`;

  const draw = () => {
    $('#add-slot').innerHTML = canEdit() ? `<button class="btn primary" id="add">${icon('plus')}Add record</button>` : '';
    $('#view-note').innerHTML = canEdit() ? '' : `<p class="form-info notice">You have View access to this shop. Ask an administrator for Edit access to change records.</p>`;
    $('#rb').innerHTML = items.length ? items.map((r) => `<tr data-id="${r.id}" class="${flashIds.has(r.id) ? 'flash' : ''}">
      <td><strong>${esc(r.part_no)}</strong></td><td class="wrap">${esc(r.description)}${r.notes ? `<br><small class="muted">${esc(r.notes)}</small>` : ''}</td>
      <td class="num">${r.quantity.toLocaleString()}</td><td>${statusBadge(r.status)}</td>
      <td>${timeTag(r.updated_at)}<br><small class="muted">by ${esc(r.updated_by || '-')}</small></td>
      <td>${canEdit() ? `<div class="row-actions"><button class="icon-btn" data-edit="${r.id}" aria-label="Edit ${esc(r.part_no)}" title="Edit">${icon('edit')}</button><button class="icon-btn" data-del="${r.id}" aria-label="Delete ${esc(r.part_no)}" title="Delete">${icon('trash')}</button></div>` : ''}</td></tr>`).join('')
      : `<tr><td colspan="6"><div class="empty"><h3>No records yet</h3><p>${canEdit() ? 'Add the first record to start tracking work in this shop.' : 'Nothing to show for these filters.'}</p></div></td></tr>`;
    flashIds = new Set();
  };
  const load = async (bg = false) => {
    const qs = new URLSearchParams(F); [...qs.keys()].forEach((k) => !qs.get(k) && qs.delete(k));
    try {
      const r = await api('GET', `/api/modules/${key}/records?${qs}`, undefined, { bg });
      if (rid !== S.renderId) return; items = r.items; level = r.level; draw();
    } catch (e) { if (!bg) toast(e.message, 'error'); }
  };
  await load();

  $('#q').addEventListener('input', debounce((e) => { F.q = e.target.value; load(); }, 300));
  $('#st').addEventListener('change', (e) => { F.status = e.target.value; load(); });
  $$('[data-exp]', root).forEach((b) => b.addEventListener('click', () => download(`/api/modules/${key}/export?fmt=${b.dataset.exp}`)));
  root.addEventListener('click', async (e) => {
    if (e.target.closest('#add')) return recordModal(mod, null, () => load());
    const ed = e.target.closest('[data-edit]'), del = e.target.closest('[data-del]');
    if (ed) return recordModal(mod, items.find((r) => r.id === +ed.dataset.edit), () => load());
    if (del) {
      const r = items.find((x) => x.id === +del.dataset.del);
      if (await confirmDialog({ title: 'Delete record', message: `Delete <strong>${esc(r.part_no)}</strong> (${esc(r.description)})? This is recorded in the audit log.`, confirmText: 'Delete record', danger: true })) {
        try { await api('DELETE', `/api/modules/${key}/records/${r.id}`); toast('Record deleted.', 'success'); load(); } catch (ex) { toast(ex.message, 'error'); load(); }
      }
    }
  });

  // Live updates: someone else changed a record in this shop.
  S.cleanups.push(bus.on('record', (ev) => {
    if (ev.module !== key) return;
    if (ev.by_id !== S.me.id) {
      toast(`${ev.by} ${ev.action} ${ev.part_no}.`, 'info', 3500); flashIds.add(ev.id);
    }
    load(true);
  }));
}

function recordModal(mod, rec, done) {
  const isNew = !rec;
  const v = rec || { part_no: '', description: '', quantity: 0, status: 'Planned', notes: '', version: 0 };
  openModal({
    title: isNew ? `Add record to ${mod.name}` : `Edit ${rec.part_no}`, wide: true,
    body: `<form id="rf" class="form-grid">
      <label class="field"><span>Part number</span><input type="text" name="part_no" maxlength="40" required value="${esc(v.part_no)}"></label>
      <label class="field"><span>Quantity</span><input type="number" name="quantity" min="0" max="10000000" step="1" required value="${esc(v.quantity)}"></label>
      <label class="field full"><span>Description</span><input type="text" name="description" maxlength="200" required value="${esc(v.description)}"></label>
      <label class="field"><span>Status</span><select name="status">${S.statuses.map((s) => `<option ${s === v.status ? 'selected' : ''}>${esc(s)}</option>`).join('')}</select></label>
      <div></div>
      <label class="field full"><span>Notes <i>(optional)</i></span><textarea name="notes" maxlength="500">${esc(v.notes || '')}</textarea></label>
      <p class="form-error full" id="rf-err" role="alert" hidden></p></form>`,
    footer: `<button class="btn" data-close>Cancel</button><button class="btn primary" type="submit" form="rf">${isNew ? 'Add record' : 'Save changes'}</button>`,
    onMount: (m) => {
      const f = m.$('#rf'), err = m.$('#rf-err'); let version = v.version;
      f.addEventListener('submit', async (e) => {
        e.preventDefault(); err.hidden = true;
        const body = { part_no: f.elements.part_no.value, description: f.elements.description.value, quantity: f.elements.quantity.value,
          status: f.elements.status.value, notes: f.elements.notes.value, version };
        try {
          if (isNew) await api('POST', `/api/modules/${mod.key}/records`, body);
          else await api('PUT', `/api/modules/${mod.key}/records/${rec.id}`, body);
          m.close(); toast(isNew ? 'Record added.' : 'Record saved.', 'success'); done();
        } catch (ex) {
          if (ex.data?.code === 'CONFLICT') {         // someone else saved first: show their values
            const l = ex.data.item; version = l.version;
            ['part_no', 'description', 'quantity', 'status', 'notes'].forEach((k) => { f.elements[k].value = l[k] ?? ''; });
          }
          err.textContent = ex.message; err.hidden = false;
        }
      });
    },
  });
}

/* ================================ Account ================================= */
export async function account(root, rid) {
  const act = await api('GET', '/api/me/activity'); if (rid !== S.renderId) return;
  const u = S.me;
  root.innerHTML = head('My account', 'Your profile, password and recent activity.') +
    `<div class="grid-2 even"><section class="card"><div class="card-head"><h2>Profile</h2></div><div class="card-body"><dl class="kv">
      <dt>Name</dt><dd>${esc(u.full_name)}</dd><dt>Username</dt><dd>${esc(u.username)}</dd><dt>Role</dt><dd>${u.role === 'admin' ? 'Admin' : 'User'}</dd>
      <dt>Department</dt><dd>${esc(u.department || '-')}</dd><dt>Email</dt><dd>${esc(u.email || '-')}</dd><dt>Previous sign-in</dt><dd>${esc(fmtTime(u.last_login))}</dd></dl>
      <h3 style="margin:1.25rem 0 .4rem">Shop access</h3><div class="chips">${S.modules.map((m) => `<span class="chip lvl-${S.perms[m.key]}">${esc(m.name.replace(' Shop', ''))}: ${LEVEL[S.perms[m.key]]}</span>`).join('')}</div></div></section>
     <section class="card"><div class="card-head"><h2>Change password</h2></div><div class="card-body">${passwordFormHtml('pw-account')}<div style="margin-top:1rem"><button class="btn primary" type="submit" form="pw-account">Change password</button></div></div></section></div>
     <section class="card" style="margin-top:1.25rem"><div class="card-head"><h2>Recent activity</h2></div><ul class="feed" id="mine"></ul></section>`;
  $('#mine').innerHTML = act.items.length ? act.items.map((e) => feedItem({ ...e, username: 'You' })).join('') : '<li><div><p class="muted">No activity yet.</p></div></li>';
  bindPasswordForm($('#pw-account'), () => toast('Password changed. Other devices were signed out.', 'success'));
}
