/* =====================================================================
 * users.js —— 用户管理页逻辑
 * 入口：DOMContentLoaded 之后调用 bootUsers()
 *
 * 设计要点：
 *   - 每次进入 users.html 都强制重新登录（不读 localStorage）
 *   - 表格操作统一通过「事件代理 onTableClick」分发
 *   - 修复旧版的「查看 / 编辑」按钮无响应问题（旧版事件绑定链断了）
 * ===================================================================== */
'use strict';

const API = '';   // 同源
const state = { token: '', users: [], selectedUser: null };

/* 不在 localStorage 缓存 token——每次进入都强制要求重新登录 */
function getToken() { return state.token; }
function setToken(t) { state.token = t || ''; }

const api = createApi(getToken, () => {
  // 401 时：清 token + 跳登录页 + 提示
  setToken('');
  showLogin();
  $('#login-hint').textContent = '登录已失效，请重新登录';
});


/* ---------- 登录 ---------- */
function showLogin() {
  $('#login-screen').classList.remove('hidden');
  $('#app').classList.add('hidden');
  $('#login-hint').textContent = '';
  $('#login-user').value = 'admin';
  $('#login-pass').value = '';
  setTimeout(() => $('#login-pass').focus(), 50);
}
function hideLogin() {
  $('#login-screen').classList.add('hidden');
  $('#app').classList.remove('hidden');
}

async function doLogin() {
  const u = $('#login-user').value.trim();
  const p = $('#login-pass').value;
  if (!u || !p) { $('#login-hint').textContent = '请输入用户名和密码'; return; }
  const btn = $('#btn-login'); btn.disabled = true; btn.textContent = '登录中…';
  try {
    const r = await fetch(API + '/api/login', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: u, password: p }),
    });
    if (!r.ok) {
      let msg = '用户名或密码错误';
      try { msg = (await r.json()).detail || msg; } catch (e) {}
      $('#login-hint').textContent = msg; return;
    }
    const d = await r.json();
    setToken(d.token);
    const me = await api('GET', '/api/me');
    if (!me.is_admin) {
      $('#login-hint').textContent = '仅管理员可访问此页面';
      setToken(''); return;
    }
    hideLogin();
    $('#admin-name').textContent = me.username;
    await loadUsers();
  } catch (e) {
    setToken('');
    $('#login-hint').textContent = '登录失败：' + e.message;
  } finally {
    btn.disabled = false; btn.textContent = '登 录';
  }
}


/* ---------- 数据加载 ---------- */
async function loadUsers() {
  try {
    state.users = await api('GET', '/api/users');
    renderTable();
  } catch (e) {
    toast('加载用户失败：' + e.message);
  }
}

async function loadStats(uid) {
  try {
    const stats = await api('GET', '/api/users/' + uid);
    const box = $(`#stats-${uid}`); if (!box) return;
    const s = stats.stats || {};
    box.innerHTML =
      `<span>角色 ${s.characters||0}</span>` +
      `<span>会话 ${s.conversations||0}</span>` +
      `<span>消息 ${s.messages||0}</span>` +
      `<span>记忆 ${s.memories||0}</span>`;
  } catch (e) { /* 单行失败不提示 */ }
}


/* ---------- 表格渲染 + 统一事件代理 ---------- */
function renderTable() {
  const tb = $('#user-table-body');
  tb.innerHTML = '';
  if (!state.users.length) {
    tb.innerHTML = '<tr><td colspan="6" class="muted">暂无用户</td></tr>';
    return;
  }
  state.users.forEach(u => {
    const tr = document.createElement('tr');
    tr.setAttribute('data-uid', u.id);
    const hasKey = !!(u.api_key && u.api_key.length);
    const keyPlaceholder = hasKey ? u.api_key : '（未配置，留空保存即为清空）';
    const inputCls = hasKey ? 'key-input' : 'key-input empty';
    tr.innerHTML = `
      <td><b>${escapeHTML(u.username)}</b>${u.role==='admin'?'<span class="tag">管理员</span>':''}</td>
      <td>${u.role||'user'}</td>
      <td>
        <div class="key-cell">
          <input class="${inputCls}" type="password" data-uid="${u.id}" value="${escapeHTML(u.api_key||'')}" placeholder="${escapeHTML(keyPlaceholder)}" autocomplete="off" />
          <button class="key-act" data-act="key-toggle" data-uid="${u.id}" title="显示/隐藏">👁</button>
          <button class="key-act" data-act="key-save"  data-uid="${u.id}">保存</button>
          <button class="key-act clear" data-act="key-clear" data-uid="${u.id}" title="清空此用户的 Key">✕</button>
        </div>
      </td>
      <td><div class="stats" id="stats-${u.id}">加载中…</div></td>
      <td style="color:var(--text-dim);font-size:12px">${u.created_at ? new Date(u.created_at).toLocaleString() : '-'}</td>
      <td>
        <div class="acts">
          <button class="btn-view" data-act="view"  data-uid="${u.id}">查看</button>
          <button class="btn-edit" data-act="edit"  data-uid="${u.id}">编辑</button>
        </div>
      </td>`;
    tb.appendChild(tr);
    loadStats(u.id);
  });
}

/* 表格区统一事件代理 —— 修复旧版 view/edit 按钮无响应的 bug */
function onTableClick(e) {
  const btn = e.target.closest('button[data-act]');
  if (!btn) return;
  const act = btn.getAttribute('data-act');
  const uid = btn.getAttribute('data-uid');
  if (!uid) return;
  switch (act) {
    case 'view':        return selectUser(uid, false);
    case 'edit':        return selectUser(uid, true);
    case 'key-toggle':  return handleKeyToggle(uid);
    case 'key-save':    return handleKeySave(uid, btn);
    case 'key-clear':   return handleKeyClear(uid, btn);
  }
}

function handleKeyToggle(uid) {
  const input = $(`input.key-input[data-uid="${uid}"]`);
  if (!input) return;
  input.type = input.type === 'password' ? 'text' : 'password';
}

async function handleKeySave(uid, btn) {
  const input = $(`input.key-input[data-uid="${uid}"]`);
  if (!input) return;
  const val = input.value;
  btn.disabled = true; btn.textContent = '保存中…';
  try {
    const r = await api('PUT', `/api/users/${uid}/api-key`, { api_key: val });
    const u = state.users.find(x => x.id === uid);
    if (u && r.user) u.api_key = r.user.api_key || '';
    toast(val ? 'Key 已保存' : 'Key 已清空');
    btn.textContent = '✓ 已保存';
    btn.classList.add('saved');
    setTimeout(() => { btn.classList.remove('saved'); btn.textContent = '保存'; btn.disabled = false; }, 1500);
  } catch (err) {
    btn.disabled = false; btn.textContent = '保存';
    toast('保存失败：' + err.message);
  }
}

async function handleKeyClear(uid, btn) {
  if (!confirm('确定清空此用户的 API Key 吗？该用户将无法调用 LLM。')) return;
  const input = $(`input.key-input[data-uid="${uid}"]`);
  if (!input) return;
  input.value = '';
  btn.disabled = true; btn.textContent = '清空中…';
  try {
    const r = await api('PUT', `/api/users/${uid}/api-key`, { api_key: '' });
    const u = state.users.find(x => x.id === uid);
    if (u && r.user) u.api_key = '';
    input.classList.add('empty');
    input.placeholder = '（未配置，留空保存即为清空）';
    toast('Key 已清空');
    btn.textContent = '✓ 已清空';
    btn.classList.add('saved');
    setTimeout(() => { btn.classList.remove('saved'); btn.textContent = '✕'; btn.disabled = false; }, 1500);
  } catch (err) {
    btn.disabled = false; btn.textContent = '✕';
    toast('清空失败：' + err.message);
  }
}


/* ---------- 详情面板 ---------- */
async function selectUser(uid, editMode = false) {
  state.selectedUser = uid;
  $$('.user-table tr').forEach(tr => tr.classList.remove('active'));
  const row = $(`.user-table tr[data-uid="${uid}"]`); if (row) row.classList.add('active');
  const root = $('#detail-root');
  root.innerHTML = '<div class="detail-panel muted">加载中…</div>';
  try {
    const data = await api('GET', `/api/users/${uid}/activity`);
    renderDetail(data, editMode);
  } catch (e) {
    root.innerHTML = `<div class="detail-panel muted">加载失败：${escapeHTML(e.message)}</div>`;
  }
}

/* 收起详情面板：清掉选中态 + 清空内容 */
function collapseDetail() {
  state.selectedUser = null;
  $$('.user-table tr').forEach(tr => tr.classList.remove('active'));
  $('#detail-root').innerHTML = '';
}

function renderDetail(data, editMode) {
  const u = data.user, s = data.stats || {}, act = data.activity || [];
  const root = $('#detail-root');
  root.innerHTML = `
    <div class="detail-panel">
      <div class="detail-head">
        <h3 style="margin:0">${escapeHTML(u.username)} ${u.role==='admin'?'<span class="tag">管理员</span>':''}</h3>
        <button class="detail-close" id="btn-collapse-detail" title="收起">✕</button>
      </div>
      <div class="detail-grid">
        <div class="entity-item"><div class="title">${s.characters||0}</div><div class="meta">创建角色</div></div>
        <div class="entity-item"><div class="title">${s.conversations||0}</div><div class="meta">会话</div></div>
        <div class="entity-item"><div class="title">${s.messages||0}</div><div class="meta">发送消息</div></div>
        <div class="entity-item"><div class="title">${s.memories||0}</div><div class="meta">相关记忆</div></div>
      </div>
      <div id="edit-form-root"></div>
      <div class="detail-tabs">
        <div class="detail-tab active" data-tab="activity">操作日志 (${act.length})</div>
        <div class="detail-tab" data-tab="characters">角色</div>
        <div class="detail-tab" data-tab="conversations">会话</div>
      </div>
      <div id="tab-content"></div>
    </div>`;
  // 收起按钮
  $('#btn-collapse-detail').addEventListener('click', collapseDetail);
  if (editMode) renderEditForm(u);
  renderTab('activity', u);
  $$('.detail-tab').forEach(t => t.addEventListener('click', () => {
    $$('.detail-tab').forEach(x => x.classList.remove('active'));
    t.classList.add('active');
    renderTab(t.getAttribute('data-tab'), u);
  }));
}

function renderEditForm(u) {
  const root = $('#edit-form-root');
  root.innerHTML = `
    <div style="margin-top:18px;border-top:1px solid var(--border);padding-top:14px">
      <h4 style="margin:0 0 12px;font-size:14px">编辑用户信息</h4>
      <form class="edit-user-form" id="form-edit-${u.id}">
        <label class="field"><span>用户名</span><input name="username" value="${escapeHTML(u.username)}" /></label>
        <label class="field"><span>角色</span>
          <select name="role">
            <option value="user" ${u.role==='user'?'selected':''}>user</option>
            <option value="admin" ${u.role==='admin'?'selected':''}>admin</option>
          </select>
        </label>
        <label class="field"><span>新密码（留空则不修改）</span><input name="password" type="password" placeholder="不修改" /></label>
        <button type="submit" class="btn primary small">保存</button>
        ${u.role!=='admin'?`<button type="button" class="btn danger small" id="btn-del-user-${u.id}">删除用户</button>`:''}
      </form>
    </div>`;
  $(`#form-edit-${u.id}`).addEventListener('submit', async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const patch = {};
    const un = (fd.get('username')||'').trim();
    if (un && un !== u.username) patch.username = un;
    const role = fd.get('role');
    if (role && role !== u.role) patch.role = role;
    const pwd = fd.get('password');
    if (pwd) patch.password = pwd;
    if (!Object.keys(patch).length) { toast('没有改动'); return; }
    try {
      await api('PUT', `/api/users/${u.id}`, patch);
      toast('用户信息已更新');
      await loadUsers();
      await selectUser(u.id, true);
    } catch (err) { toast('更新失败：' + err.message); }
  });
  const delBtn = $(`#btn-del-user-${u.id}`);
  if (delBtn) delBtn.addEventListener('click', async () => {
    if (!confirm(`确定删除用户 ${u.username} 吗？其创建的角色、会话等数据不会自动删除，但后续无法以此账户登录。`)) return;
    try {
      await api('DELETE', `/api/users/${u.id}`);
      toast('用户已删除');
      state.selectedUser = null;
      await loadUsers();
      $('#detail-root').innerHTML = '';
    } catch (err) { toast('删除失败：' + err.message); }
  });
}

async function renderTab(tab, u) {
  const box = $('#tab-content');
  box.innerHTML = '<div class="muted">加载中…</div>';
  if (tab === 'activity') {
    const data = await api('GET', `/api/users/${u.id}/activity`);
    const list = data.activity || [];
    if (!list.length) { box.innerHTML = '<div class="muted">暂无操作日志</div>'; return; }
    box.innerHTML = '<div class="activity-list"></div>';
    const ul = box.querySelector('.activity-list');
    list.forEach(a => {
      const el = document.createElement('div'); el.className = 'activity-item';
      el.innerHTML = `<span class="time">${a.created_at?new Date(a.created_at).toLocaleString():'-'}</span><span class="act">${escapeHTML(a.action)}</span><span class="detail">${escapeHTML(a.detail||'')}</span>`;
      ul.appendChild(el);
    });
  } else if (tab === 'characters') {
    const chars = await api('GET', `/api/users/${u.id}/characters`);
    if (!chars.length) { box.innerHTML = '<div class="muted">该用户尚未创建角色</div>'; return; }
    box.innerHTML = '<div class="entity-list"></div>';
    const ul = box.querySelector('.entity-list');
    chars.forEach(c => {
      const el = document.createElement('div'); el.className = 'entity-item';
      el.innerHTML = `<div class="title">${escapeHTML(c.name)}</div><div class="meta">${escapeHTML((c.persona||'').slice(0,80))}${(c.persona||'').length>80?'...':''}</div>`;
      ul.appendChild(el);
    });
  } else if (tab === 'conversations') {
    const convs = await api('GET', `/api/users/${u.id}/conversations`);
    if (!convs.length) { box.innerHTML = '<div class="muted">该用户尚未创建会话</div>'; return; }
    box.innerHTML = '<div class="entity-list"></div>';
    const ul = box.querySelector('.entity-list');
    convs.forEach(v => {
      const el = document.createElement('div'); el.className = 'entity-item';
      el.innerHTML = `<div class="title">${escapeHTML(v.title||'新对话')}</div><div class="meta">${v.message_count||0} 条消息 · ${v.created_at?new Date(v.created_at).toLocaleString():'-'}</div>`;
      ul.appendChild(el);
    });
  }
}


/* ---------- 启动 ---------- */
function bootUsers() {
  // 事件代理：表格内的所有 [data-act] 按钮
  $('#user-table-body').addEventListener('click', onTableClick);
  // 登录按钮
  $('#btn-login').addEventListener('click', doLogin);
  $('#login-pass').addEventListener('keydown', (e) => { if (e.key === 'Enter') doLogin(); });
  $('#login-user').addEventListener('keydown', (e) => { if (e.key === 'Enter') $('#login-pass').focus(); });

  // 默认强制显示登录页（不读 localStorage）
  showLogin();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', bootUsers);
} else {
  bootUsers();
}
