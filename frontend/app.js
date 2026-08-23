/* =====================================================================
 * app.js —— 沉浸对话 前端逻辑（原生 JS，无构建步骤）
 * 接口基准：同域 /api/...（后端在 8000 端口托管本页面，故直接用相对路径）
 * ===================================================================== */
'use strict';

const API = ''; // 同源，留空即可；若前后端分离可改为 'http://localhost:8000'
const TOKEN_KEY = 'chat_token';

function getToken() { return localStorage.getItem(TOKEN_KEY) || ''; }
function setToken(t) { if (t) localStorage.setItem(TOKEN_KEY, t); else localStorage.removeItem(TOKEN_KEY); }

const state = {
  config: {},
  characters: [],
  conversations: [],
  currentConv: null,      // 当前会话对象
  currentCharacter: null, // 当前角色对象
  memories: [],
  editingCharId: null,    // 正在编辑的角色 id（null=新建）
  username: '',           // 当前登录用户名
  isAdmin: false,         // 是否为管理员
};

// 编辑角色时暂存「参考图」列表（dataURL），保存时随角色卡一起提交
let editingRefs = [];

/* ---------- 工具 ---------- */
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

function api(method, path, body) {
  const opt = { method, headers: {} };
  const t = getToken();
  if (t) opt.headers['Authorization'] = 'Bearer ' + t;
  if (body !== undefined) {
    opt.headers['Content-Type'] = 'application/json';
    opt.body = JSON.stringify(body);
  }
  return fetch(API + path, opt).then(async (r) => {
    if (r.status === 401) {
      setToken('');
      showLogin();
      throw new Error('登录已失效，请重新登录');
    }
    if (!r.ok) {
      let msg = `请求失败 (${r.status})`;
      try { msg = (await r.json()).detail || msg; } catch (e) {}
      throw new Error(msg);
    }
    const ct = r.headers.get('content-type') || '';
    return ct.includes('application/json') ? r.json() : r;
  });
}

function toast(msg) {
  const t = $('#toast');
  t.textContent = msg;
  t.classList.remove('hidden');
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.add('hidden'), 2600);
}

function avatarHTML(avatar, cls = 'avatar') {
  if (avatar && (avatar.startsWith('data:image') || avatar.startsWith('http'))) {
    return `<div class="${cls}"><img src="${avatar}" alt=""></div>`;
  }
  return `<div class="${cls}">${avatar || '🤖'}</div>`;
}

function escapeHTML(s) {
  return String(s).replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

/* ---------- 弹窗控制 ---------- */
function openModal(id) {
  $('#overlay').classList.remove('hidden');
  $('#' + id).classList.remove('hidden');
}
function closeModals() {
  $('#overlay').classList.add('hidden');
  $$('.modal').forEach((m) => m.classList.add('hidden'));
  // 移动端：弹窗关闭后顺势收起侧边栏，避免下层抽屉遮挡聊天区
  closeSidebar();
}
$('#overlay').addEventListener('click', closeModals);
$$('[data-close]').forEach((b) => b.addEventListener('click', closeModals));

/* ---------- 主题 ---------- */
function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme || 'dark');
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute('content', theme === 'light' ? '#ffffff' : '#0f0f14');
}
$('#btn-theme').addEventListener('click', async () => {
  const next = (state.config.theme === 'light') ? 'dark' : 'light';
  state.config.theme = next;
  applyTheme(next);
  try { await api('PUT', '/api/config', { theme: next }); } catch (e) {}
});

/* =====================================================================
 * 登录 / 鉴权
 * ===================================================================== */
function showLogin() {
  $('#login-screen').classList.remove('hidden');
  $('#app').classList.add('hidden');
  $('#login-hint').textContent = '';
  $('#login-user').value = 'admin';
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
  const btn = $('#btn-login');
  btn.disabled = true; btn.textContent = '登录中…';
  try {
    const r = await fetch(API + '/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: u, password: p }),
    });
    if (!r.ok) {
      let msg = '用户名或密码错误';
      try { msg = (await r.json()).detail || msg; } catch (e) {}
      $('#login-hint').textContent = msg;
      return;
    }
    const data = await r.json();
    setToken(data.token);
    hideLogin();
    await init();
  } catch (e) {
    $('#login-hint').textContent = '登录失败：' + e.message;
  } finally {
    btn.disabled = false; btn.textContent = '登 录';
  }
}
$('#btn-login').addEventListener('click', doLogin);
$('#login-pass').addEventListener('keydown', (e) => { if (e.key === 'Enter') doLogin(); });
$('#login-user').addEventListener('keydown', (e) => { if (e.key === 'Enter') doLogin(); });

$('#btn-logout').addEventListener('click', async () => {
  try { await api('POST', '/api/logout'); } catch (e) {}
  setToken('');
  state.username = '';
  state.isAdmin = false;
  updateUserButton();
  closeModals();
  showLogin();
  toast('已退出登录');
});

function updateUserButton() {
  const btn = $('#btn-user');
  if (!btn) return;
  if (state.username) {
    btn.textContent = state.isAdmin ? '👤 ' + state.username : '👤';
    btn.title = '当前用户：' + state.username + (state.isAdmin ? '（管理员）' : '');
  } else {
    btn.textContent = '🔒';
    btn.title = '未登录';
  }
}

$('#btn-user').addEventListener('click', () => {
  if (state.username) {
    if (confirm(`当前登录用户：${state.username}${state.isAdmin ? '（管理员）' : ''}\n\n要退出登录吗？`)) {
      $('#btn-logout').click();
    }
  } else {
    showLogin();
  }
});

/* =====================================================================
 * 初始化加载
 * ===================================================================== */
async function init() {
  // 先注册 Service Worker，确保即使当前 token 失效，也能立即升级到新版
  registerSW();

  // 未登录先展示登录屏
  if (!getToken()) { showLogin(); return; }
  try {
    // 同时拉配置和当前用户信息，任一失败都会进入 catch
    const [cfg, me] = await Promise.all([
      api('GET', '/api/config'),
      api('GET', '/api/me'),
    ]);
    state.config = cfg;
    state.username = me.username || '';
    state.isAdmin = !!me.is_admin;
    updateUserButton();
  } catch (e) {
    // 401 会清空 token 并触发 showLogin；其它错误也回落到登录屏
    setToken('');
    showLogin();
    return;
  }
  applyTheme(state.config.theme);

  await Promise.all([loadCharacters(), loadConversations()]);

  // 首次运行无角色时，写入一个示例角色，方便立即体验
  if (state.characters.length === 0) {
    await seedExampleCharacter();
    await loadCharacters();
  }
  renderCharacters();
  renderConversations();
}

// 兜底：如果因为旧版 Service Worker 缓存导致 app 已显示但 token 为空，强制回到登录屏
setTimeout(() => {
  if (!getToken() && !$('#app').classList.contains('hidden')) {
    showLogin();
  }
}, 300);

async function seedExampleCharacter() {
  const demo = {
    name: '小柚',
    avatar: '🍊',
    persona: '你叫小柚，19 岁，隔壁班的学妹，性格开朗又有点小傲娇，喜欢喝橙汁，偷偷考研中。',
    personality: '活泼、嘴硬心软、偶尔撒娇、爱用语气词（呀、嘛、哼）。',
    speaking_style: '口语化，短句为主，带点俏皮，偶尔用表情符号。',
    example_dialogues: '用户：在干嘛？\n小柚：哼，复习呢，才不是为了考试……你管得真宽呀。',
    world_setting: '',
    greeting: '诶？你来找我啦～今天复习好累哦，陪我说说话嘛。',
    tags: '校园,恋爱,日常',
  };
  try { await api('POST', '/api/characters', demo); } catch (e) {}
}

/* =====================================================================
 * 角色库
 * ===================================================================== */
async function loadCharacters() {
  state.characters = await api('GET', '/api/characters');
}
async function loadConversations() {
  state.conversations = await api('GET', '/api/conversations');
}

function renderCharacters() {
  const grid = $('#char-grid');
  grid.innerHTML = '';
  state.characters.forEach((c) => {
    const desc = c.persona ? c.persona.slice(0, 40) : (c.tags || '暂无简介');
    const el = document.createElement('div');
    el.className = 'char-card';
    el.innerHTML = `
      ${avatarHTML(c.avatar, 'avatar')}
      <div class="cname">${escapeHTML(c.name)}</div>
      <div class="cdesc">${escapeHTML(desc)}</div>
      <div class="cacts">
        <button class="mini-btn" data-act="edit">编辑</button>
        <button class="mini-btn" data-act="del">删除</button>
      </div>`;
    el.addEventListener('click', (e) => {
      const act = e.target.getAttribute('data-act');
      if (act === 'edit') { openCharEditor(c.id); }
      else if (act === 'del') { deleteCharacter(c.id); }
      else { startConversation(c.id); }
    });
    grid.appendChild(el);
  });
  // 同步渲染侧边栏的角色列表（移动端用），让侧边栏「角色库」tab 也能直接点选/编辑角色
  renderSidebarCharacters();
}

/* 侧边栏内的角色列表：紧凑列表项，点击直接开聊，「编辑」按钮进编辑器 */
function renderSidebarCharacters() {
  const list = $('#char-list');
  if (!list) return;
  list.innerHTML = '';
  if (state.characters.length === 0) {
    // 空状态：直接给出「新建角色」入口，移动端也可一键触达
    const empty = document.createElement('div');
    empty.style.cssText = 'color:var(--text-dim);font-size:12px;padding:14px 10px;text-align:center;display:flex;flex-direction:column;gap:10px;align-items:center;';
    empty.innerHTML = '<div>还没有角色</div>';
    const btn = document.createElement('button');
    btn.className = 'btn primary small';
    btn.textContent = '＋ 新建角色';
    btn.addEventListener('click', () => openCharEditor(null));
    empty.appendChild(btn);
    list.appendChild(empty);
    return;
  }
  state.characters.forEach((c) => {
    const desc = c.persona ? c.persona.slice(0, 30) : (c.tags || '暂无简介');
    const el = document.createElement('div');
    el.className = 'char-item';
    el.innerHTML = `
      ${avatarHTML(c.avatar, 'avatar')}
      <div class="info">
        <div class="name">${escapeHTML(c.name)}</div>
        <div class="desc">${escapeHTML(desc)}</div>
      </div>
      <div class="acts">
        <button class="mini-btn" data-act="edit" title="编辑">编辑</button>
      </div>`;
    el.addEventListener('click', (e) => {
      if (e.target.getAttribute('data-act') === 'edit') { openCharEditor(c.id); return; }
      // 点击角色卡片 → 直接开始/恢复对话（侧边栏会自动收起）
      startConversation(c.id);
    });
    list.appendChild(el);
  });
}

function renderConversations() {
  const list = $('#conv-list');
  list.innerHTML = '';
  if (state.conversations.length === 0) {
    list.innerHTML = '<div style="color:var(--text-dim);font-size:12px;padding:8px;">还没有对话，点「新建对话」开始</div>';
    return;
  }
  state.conversations.forEach((v) => {
    const ch = state.characters.find((c) => c.id === v.character_id) || {};
    const el = document.createElement('div');
    el.className = 'conv-item' + (state.currentConv && state.currentConv.id === v.id ? ' active' : '');
    el.innerHTML = `
      ${avatarHTML(ch.avatar, 'avatar')}
      <div class="conv-meta">
        <div class="conv-title">${escapeHTML(v.title || '新对话')}</div>
        <div class="conv-sub">${escapeHTML(ch.name || '未知角色')} · ${v.message_count || 0} 条</div>
      </div>
      <button class="conv-del" title="删除">🗑</button>`;
    el.addEventListener('click', (e) => {
      if (e.target.classList.contains('conv-del')) { deleteConversation(v.id); return; }
      openConversation(v.id);
    });
    list.appendChild(el);
  });
}

/* 侧边栏 tab 切换 */
$$('.sidebar-tabs .tab').forEach((t) => {
  t.addEventListener('click', () => {
    $$('.sidebar-tabs .tab').forEach((x) => x.classList.remove('active'));
    t.classList.add('active');
    const tab = t.getAttribute('data-tab');
    $('#conv-list').classList.toggle('hidden', tab !== 'conv');
    $('#char-list').classList.toggle('hidden', tab !== 'char');
    // 移动端切换 tab 后自动收起侧边栏
    closeSidebar();
  });
});

/* 移动端：侧边栏抽屉开关 */
function isMobile() { return window.matchMedia('(max-width: 720px)').matches; }
function openSidebar()  { document.body.classList.add('sidebar-open'); }
function closeSidebar() { document.body.classList.remove('sidebar-open'); }
function toggleSidebar() {
  if (document.body.classList.contains('sidebar-open')) closeSidebar();
  else openSidebar();
}
$('#btn-menu-toggle').addEventListener('click', (e) => {
  e.stopPropagation();
  toggleSidebar();
});
$('#sidebar-backdrop').addEventListener('click', closeSidebar);
// Esc 关闭侧边栏
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && document.body.classList.contains('sidebar-open')) closeSidebar();
});

$('#btn-new-chat').addEventListener('click', () => {
  $$('.sidebar-tabs .tab').forEach((x) => x.classList.toggle('active', x.getAttribute('data-tab') === 'char'));
  $('#conv-list').classList.add('hidden');
  $('#char-list').classList.remove('hidden');
  openCharsModal();
});

function openCharsModal() {
  renderCharacters();
  openModal('chars-modal');
}

/* 新建角色 */
$('#btn-new-char').addEventListener('click', () => openCharEditor(null));
function openCharEditor(id) {
  state.editingCharId = id;
  const c = id ? state.characters.find((x) => x.id === id) : {};
  $('#char-edit-title').textContent = id ? '编辑角色' : '新建角色';
  $('#ce-name').value = c.name || '';
  $('#ce-avatar').value = c.avatar && !c.avatar.startsWith('data:image') ? c.avatar : '';
  $('#ce-avatar-preview').innerHTML = avatarHTML(c.avatar || '🙂', 'avatar preview');
  $('#ce-persona').value = c.persona || '';
  $('#ce-personality').value = c.personality || '';
  $('#ce-speaking_style').value = c.speaking_style || '';
  $('#ce-world_setting').value = c.world_setting || '';
  $('#ce-example_dialogues').value = c.example_dialogues || '';
  $('#ce-greeting').value = c.greeting || '';
  $('#ce-tags').value = c.tags || '';
  // 参考图：从角色卡载入，编辑期间存于 editingRefs
  editingRefs = Array.isArray(c.refs) ? c.refs.slice() : [];
  renderRefs();
  openModal('char-edit-modal');
}

/* 渲染参考图网格（角色编辑器中） */
function renderRefs() {
  const grid = $('#ce-refs');
  if (!grid) return;
  grid.innerHTML = '';
  editingRefs.forEach((src, i) => {
    const item = document.createElement('div');
    item.className = 'ref-item';
    item.innerHTML = `<img src="${src}" alt="参考图" /><button class="ref-del" title="删除" type="button">✕</button>`;
    item.querySelector('.ref-del').addEventListener('click', () => {
      editingRefs.splice(i, 1);
      renderRefs();
    });
    grid.appendChild(item);
  });
}

/* 参考图上传：多张 dataURL 追加到 editingRefs */
$('#ce-refs-upload').addEventListener('click', () => $('#ce-refs-file').click());
$('#ce-refs-file').addEventListener('change', (e) => {
  const files = Array.from(e.target.files || []);
  if (!files.length) return;
  let pending = files.length;
  files.forEach((file) => {
    const reader = new FileReader();
    reader.onload = () => {
      editingRefs.push(reader.result);
      if (--pending === 0) renderRefs();
    };
    reader.readAsDataURL(file);
  });
  e.target.value = '';
});

/* 头像预览同步 */
$('#ce-avatar').addEventListener('input', (e) => {
  $('#ce-avatar-preview').innerHTML = avatarHTML(e.target.value || '🙂', 'avatar preview');
});
$('#ce-upload').addEventListener('click', () => $('#ce-upload-file').click());
$('#ce-upload-file').addEventListener('change', (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    const data = reader.result;
    // 头像存为 dataURL，随角色卡导出可携带
    $('#ce-avatar').value = data;
    $('#ce-avatar-preview').innerHTML = `<div class="avatar preview"><img src="${data}"></div>`;
  };
  reader.readAsDataURL(file);
});

/* 保存角色 */
$('#btn-save-char').addEventListener('click', async () => {
  const payload = {
    name: $('#ce-name').value.trim() || '未命名角色',
    avatar: $('#ce-avatar').value.trim(),
    persona: $('#ce-persona').value,
    personality: $('#ce-personality').value,
    speaking_style: $('#ce-speaking_style').value,
    world_setting: $('#ce-world_setting').value,
    example_dialogues: $('#ce-example_dialogues').value,
    greeting: $('#ce-greeting').value,
    tags: $('#ce-tags').value,
    refs: editingRefs,
  };
  try {
    if (state.editingCharId) {
      await api('PUT', '/api/characters/' + state.editingCharId, payload);
      toast('角色已更新');
    } else {
      await api('POST', '/api/characters', payload);
      toast('角色已创建');
    }
    closeModals();
    await loadCharacters();
    renderCharacters();
  } catch (e) { toast('保存失败：' + e.message); }
});

/* 导出角色卡 */
$('#btn-export-char').addEventListener('click', async () => {
  if (!state.editingCharId) { toast('请先保存角色再导出'); return; }
  try {
    const c = await api('GET', '/api/characters/' + state.editingCharId + '/export');
    const blob = new Blob([JSON.stringify(c, null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = (c.name || 'character') + '.json';
    a.click();
    URL.revokeObjectURL(a.href);
  } catch (e) { toast('导出失败：' + e.message); }
});

/* 导入角色卡 */
$('#btn-import-char').addEventListener('click', () => $('#import-file').click());
$('#import-file').addEventListener('change', async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  try {
    const text = await file.text();
    const obj = JSON.parse(text);
    const payload = {
      name: obj.name || '导入角色',
      avatar: obj.avatar || '',
      persona: obj.persona || '',
      personality: obj.personality || '',
      speaking_style: obj.speaking_style || '',
      world_setting: obj.world_setting || '',
      example_dialogues: obj.example_dialogues || '',
      greeting: obj.greeting || '',
      tags: obj.tags || '',
      refs: Array.isArray(obj.refs) ? obj.refs : [],
    };
    await api('POST', '/api/characters/import', payload);
    toast('角色已导入');
    await loadCharacters();
    renderCharacters();
    e.target.value = '';
  } catch (err) { toast('导入失败：文件格式不正确'); }
});

async function deleteCharacter(id) {
  if (!confirm('确定删除该角色？相关会话与记忆也会一并删除。')) return;
  try {
    await api('DELETE', '/api/characters/' + id);
    await loadCharacters();
    renderCharacters();
    if (state.currentCharacter && state.currentCharacter.id === id) {
      state.currentCharacter = null; state.currentConv = null;
      renderConversations(); clearChat();
    }
    toast('已删除');
  } catch (e) { toast('删除失败：' + e.message); }
}

/* =====================================================================
 * 会话 / 聊天
 * ===================================================================== */
async function startConversation(characterId) {
  try {
    const conv = await api('POST', '/api/conversations', { character_id: characterId });
    closeModals();
    await loadConversations();
    renderConversations();
    openConversation(conv.id);
  } catch (e) { toast('创建对话失败：' + e.message); }
}

async function openConversation(vid) {
  try {
    const conv = await api('GET', '/api/conversations/' + vid);
    state.currentConv = conv;
    state.currentCharacter = state.characters.find((c) => c.id === conv.character_id) || null;
    applyBackground(conv.background || '');
    renderHead();
    renderMessages(conv.messages || []);
    renderConversations();
    closeSidebar(); // 移动端进入对话后自动收起侧边栏
  } catch (e) { toast('打开失败：' + e.message); }
}

/* 应用聊天背景（图片 URL / dataURL / CSS 渐变） */
function applyBackground(bg) {
  const box = $('#messages');
  if (!box) return;
  if (!bg) {
    box.style.background = '';
    box.classList.remove('has-bg');
    return;
  }
  // 以 url() 包裹图片地址；若是 dataURL 或 http(s) 则作背景图，否则当作原始 CSS
  if (/^(https?:|data:)/.test(bg.trim())) {
    box.style.background = `center / cover no-repeat url("${bg.trim()}")`;
  } else {
    box.style.background = bg;
  }
  box.classList.add('has-bg');
}

function renderHead() {
  const c = state.currentCharacter;
  if (!c) return;
  $('#head-avatar').outerHTML = avatarHTML(c.avatar, 'avatar').replace('class="avatar"', 'id="head-avatar" class="avatar"');
  $('#head-name').textContent = c.name || '角色';
  const cnt = (state.currentConv && state.currentConv.message_count) || 0;
  $('#head-sub').textContent = `已聊 ${cnt} 条 · 点击「记忆」查看 TA 记住的事`;
}

function clearChat() {
  $('#messages').innerHTML = `
    <div class="empty-hint">
      <div class="big-emoji">💬</div>
      <p>选择一个角色，开始沉浸式对话</p>
      <p class="sub">支持日常 · 恋爱 · 脑洞剧情，AI 会记住你们的故事</p>
    </div>`;
  $('#head-name').textContent = '未选择角色';
  $('#head-sub').textContent = '从「角色库」选择角色开始对话';
  $('#head-avatar').outerHTML = '<div class="avatar" id="head-avatar">🤖</div>';
}

function renderMessages(messages) {
  const box = $('#messages');
  box.innerHTML = '';
  if (!messages || messages.length === 0) {
    clearChat();
    return;
  }
  messages.forEach((m) => renderMsgEl(m, false));
  box.scrollTop = box.scrollHeight;
}

/* 渲染一条完整消息（含已生成的配图与角色消息的「生图」按钮） */
function renderMsgEl(m, scroll = true) {
  const box = $('#messages');
  const empty = box.querySelector('.empty-hint');
  if (empty) empty.remove();
  const c = state.currentCharacter || {};
  const av = m.role === 'user' ? '🙂' : (c.avatar || '🤖');
  const wrap = document.createElement('div');
  wrap.className = 'msg ' + (m.role === 'user' ? 'user' : 'bot');
  wrap.dataset.mid = m.id;
  wrap.innerHTML = `
    ${avatarHTML(av, 'avatar')}
    <div class="bubble">${escapeHTML(m.content)}</div>`;
  // 配图区
  const imgWrap = document.createElement('div');
  imgWrap.className = 'msg-image';
  if (m.image) {
    imgWrap.innerHTML = `<img src="${m.image}" alt="配图" />`;
  }
  wrap.appendChild(imgWrap);
  // 角色（assistant）消息：底部小生图按钮，支持生成/重新生成
  if (m.role === 'assistant') {
    const genBtn = document.createElement('button');
    genBtn.className = 'msg-gen-img';
    genBtn.textContent = m.image ? '🎨 重新生图' : '🎨 生图';
    genBtn.addEventListener('click', () => generateMessageImage(m.id, imgWrap, genBtn));
    wrap.appendChild(genBtn);
  }
  box.appendChild(wrap);
  if (scroll) box.scrollTop = box.scrollHeight;
  return wrap;
}

function appendMessage(role, content, scroll = true) {
  const box = $('#messages');
  const empty = box.querySelector('.empty-hint');
  if (empty) empty.remove();
  const c = state.currentCharacter || {};
  const av = role === 'user' ? '🙂' : (c.avatar || '🤖');
  const wrap = document.createElement('div');
  wrap.className = 'msg ' + (role === 'user' ? 'user' : 'bot');
  wrap.innerHTML = `
    ${avatarHTML(av, 'avatar')}
    <div class="bubble">${escapeHTML(content)}</div>`;
  box.appendChild(wrap);
  if (scroll) box.scrollTop = box.scrollHeight;
  return wrap.querySelector('.bubble');
}

/* 为某条角色消息生成配图（基于角色设定 + 该消息内容 + 角色头像/参考图） */
async function generateMessageImage(mid, imgWrap, btn) {
  if (btn.disabled) return;
  btn.disabled = true;
  const old = btn.textContent;
  btn.textContent = '⏳ 生成中…';
  imgWrap.innerHTML = '<div class="msg-img-loading">正在生成配图…</div>';
  try {
    const r = await api('POST', '/api/messages/' + mid + '/image');
    if (r.ok && r.image) {
      imgWrap.innerHTML = `<img src="${r.image}" alt="配图" />`;
      btn.textContent = '🎨 重新生图';
    } else {
      imgWrap.innerHTML = '';
      toast('生图失败：' + (r.error || '未知错误'));
      btn.textContent = old;
    }
  } catch (e) {
    imgWrap.innerHTML = '';
    toast('生图失败：' + e.message);
    btn.textContent = old;
  } finally {
    btn.disabled = false;
  }
}

/* 渲染「心理活动 / 动作」旁白（沉浸式） */
function appendInner(content, scroll = true) {
  const box = $('#messages');
  const empty = box.querySelector('.empty-hint');
  if (empty) empty.remove();
  const el = document.createElement('div');
  el.className = 'inner-thought';
  el.textContent = '💭 ' + content;
  box.appendChild(el);
  if (scroll) box.scrollTop = box.scrollHeight;
}

/* 发送消息（流式） */
let sending = false;
async function sendMessage() {
  const input = $('#input');
  const text = input.value.trim();
  if (!text || sending) return;
  if (!state.currentConv) { toast('请先选择一个角色开始对话'); openCharsModal(); return; }

  sending = true;
  $('#btn-send').disabled = true;
  input.value = ''; autoGrow(input);

  appendMessage('user', text);
  const bubble = appendMessage('assistant', '');
  bubble.innerHTML = '<span class="cursor"></span>';

  const body = { conversation_id: state.currentConv.id, user_message: text };
  try {
    const headers = { 'Content-Type': 'application/json' };
    const t = getToken();
    if (t) headers['Authorization'] = 'Bearer ' + t;
    const resp = await fetch(API + '/api/chat', {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
    });
    if (resp.status === 401) { setToken(''); showLogin(); throw new Error('登录已失效，请重新登录'); }
    if (!resp.ok) throw new Error('接口错误 ' + resp.status);
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    let full = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop();
      for (const line of lines) {
        if (!line.startsWith('data:')) continue;
        const json = line.slice(5).trim();
        if (!json) continue;
        try {
          const evt = JSON.parse(json);
          if (evt.type === 'delta') {
            full += evt.content;
            bubble.textContent = full;
            bubble.appendChild(Object.assign(document.createElement('span'), { className: 'cursor' }));
            $('#messages').scrollTop = $('#messages').scrollHeight;
          } else if (evt.type === 'error') {
            bubble.textContent = '⚠️ ' + evt.message;
          } else if (evt.type === 'done') {
            bubble.textContent = evt.content;
            full = evt.content;
          } else if (evt.type === 'inner') {
            appendInner(evt.content);
          } else if (evt.type === 'summary') {
            if (evt.added > 0) toast(`已自动总结 ${evt.added} 条长期记忆`);
          }
        } catch (e) {}
      }
    }
    // 刷新会话列表（消息数/标题可能变化）
    await loadConversations();
    renderConversations();
    if (state.currentConv) {
      const updated = state.conversations.find((v) => v.id === state.currentConv.id);
      if (updated) { state.currentConv = updated; renderHead(); }
    }
  } catch (e) {
    bubble.textContent = '⚠️ 发送失败：' + e.message;
  } finally {
    sending = false;
    $('#btn-send').disabled = false;
  }
}

$('#btn-send').addEventListener('click', sendMessage);
$('#input').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
});
function autoGrow(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 140) + 'px';
}
$('#input').addEventListener('input', (e) => autoGrow(e.target));

/* 移动端软键盘处理：键盘弹出时把消息区滚到底，并让 composer 跟随 visualViewport
   visualViewport 在 iOS / Android Chrome / Edge 均可拿到键盘弹出后的可见高度。*/
(function setupMobileKeyboard() {
  const vv = window.visualViewport;
  if (!vv) return;
  // 用 --vv-height 暴露当前可见视口高度，供 CSS（dvh）之外的精细调整使用
  function sync() {
    document.documentElement.style.setProperty('--vv-height', vv.height + 'px');
  }
  vv.addEventListener('resize', sync);
  vv.addEventListener('scroll', sync);
  sync();
})();
/* 输入框聚焦（键盘弹出）后，延迟滚动消息到底，保证最后一条可见 */
$('#input').addEventListener('focus', () => {
  setTimeout(() => {
    const box = $('#messages');
    if (box) box.scrollTop = box.scrollHeight;
  }, 250);
});

/* 清空上下文 */
$('#btn-clear').addEventListener('click', async () => {
  if (!state.currentConv) return;
  if (!confirm('清空当前会话的全部对话记录？（角色记忆保留）')) return;
  try {
    await api('POST', '/api/conversations/' + state.currentConv.id + '/clear');
    await openConversation(state.currentConv.id);
    toast('上下文已清空');
  } catch (e) { toast('清空失败：' + e.message); }
});

/* 删除会话 */
$('#btn-del-conv').addEventListener('click', async () => {
  if (!state.currentConv) return;
  if (!confirm('删除当前会话？此操作不可恢复。')) return;
  try {
    await deleteConversation(state.currentConv.id);
  } catch (e) { toast('删除失败：' + e.message); }
});

async function deleteConversation(vid) {
  await api('DELETE', '/api/conversations/' + vid);
  if (state.currentConv && state.currentConv.id === vid) {
    state.currentConv = null; state.currentCharacter = null;
    clearChat();
  }
  await loadConversations();
  renderConversations();
  toast('会话已删除');
}

/* =====================================================================
 * 聊天背景
 * ===================================================================== */
const BG_PRESETS = [
  'linear-gradient(135deg,#1a1530,#2a1f4a)',
  'linear-gradient(135deg,#0f172a,#1e293b)',
  'linear-gradient(135deg,#2a1a12,#3a2418)',
  'linear-gradient(135deg,#0f2027,#203a43)',
  'linear-gradient(135deg,#2d1b3d,#4a2c5a)',
  'linear-gradient(135deg,#1f1f2e,#3a2f3f)',
];
let pendingBg = '';

function renderBgPresets() {
  const box = $('#bg-presets');
  box.innerHTML = '';
  BG_PRESETS.forEach((g) => {
    const el = document.createElement('div');
    el.className = 'bg-swatch';
    el.style.background = g;
    el.addEventListener('click', () => {
      pendingBg = g;
      $$('.bg-swatch').forEach((s) => s.classList.remove('active'));
      el.classList.add('active');
    });
    box.appendChild(el);
  });
}

$('#btn-bg').addEventListener('click', () => {
  if (!state.currentConv) { toast('请先选择角色开始对话'); return; }
  pendingBg = (state.currentConv.background || '');
  renderBgPresets();
  // 若当前是已上传的图片 dataURL，预览出来
  if (pendingBg && /^(https?:|data:)/.test(pendingBg.trim())) {
    const el = document.createElement('div');
    el.className = 'bg-swatch active';
    el.style.background = `center / cover no-repeat url("${pendingBg.trim()}")`;
    $('#bg-presets').appendChild(el);
  }
  openModal('bg-modal');
});

$('#bg-upload-btn').addEventListener('click', () => $('#bg-upload-file').click());
$('#bg-upload-file').addEventListener('change', (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    pendingBg = reader.result;
    $$('.bg-swatch').forEach((s) => s.classList.remove('active'));
    const el = document.createElement('div');
    el.className = 'bg-swatch active';
    el.style.background = `center / cover no-repeat url("${pendingBg}")`;
    $('#bg-presets').appendChild(el);
  };
  reader.readAsDataURL(file);
});

$('#bg-clear-btn').addEventListener('click', () => {
  pendingBg = '';
  $$('.bg-swatch').forEach((s) => s.classList.remove('active'));
});

$('#btn-save-bg').addEventListener('click', async () => {
  if (!state.currentConv) return;
  try {
    await api('PUT', '/api/conversations/' + state.currentConv.id + '/background', { background: pendingBg });
    state.currentConv.background = pendingBg;
    applyBackground(pendingBg);
    closeModals();
    toast('背景已应用');
  } catch (e) { toast('设置失败：' + e.message); }
});

/* =====================================================================
 * 人物当前状态图
 * ===================================================================== */
$('#btn-portrait').addEventListener('click', () => {
  if (!state.currentConv) { toast('请先选择角色开始对话'); return; }
  openModal('portrait-modal');
});

$('#btn-gen-portrait').addEventListener('click', async () => {
  if (!state.currentConv) return;
  const btn = $('#btn-gen-portrait');
  const box = $('#portrait-box');
  const desc = $('#portrait-desc');
  btn.disabled = true; btn.textContent = '生成中…';
  box.innerHTML = '<div class="portrait-placeholder">正在生成，阿里云百炼等异步接口可能需要 10–30 秒…</div>';
  desc.textContent = '';
  try {
    const r = await api('POST', '/api/conversations/' + state.currentConv.id + '/portrait');
    desc.textContent = r.description || '';
    if (r.image) {
      box.innerHTML = `<img class="portrait-img" src="${r.image}" alt="人物状态" />`;
    } else if (r.image_error) {
      // 已配置但调用失败，展示具体错误而不是误报“未配置”
      box.innerHTML = '<div class="portrait-placeholder">图像生成失败：' + escapeHTML(r.image_error) + '</div>';
      toast('图像生成失败：' + r.image_error);
    } else {
      box.innerHTML = '<div class="portrait-placeholder">未配置图像生成服务，已生成文字状态描述</div>';
      toast('未配置图像接口，仅展示文字状态（可在设置中填写图像 API）');
    }
  } catch (e) {
    box.innerHTML = '<div class="portrait-placeholder">生成失败：' + escapeHTML(e.message) + '</div>';
  } finally {
    btn.disabled = false; btn.textContent = '生成';
  }
});

/* =====================================================================
 * 记忆面板（复刻猫箱记忆机制）
 * ===================================================================== */
$('#btn-memory').addEventListener('click', async () => {
  if (!state.currentCharacter) { toast('请先选择角色'); return; }
  await loadMemories();
  openModal('memory-modal');
});

async function loadMemories() {
  if (!state.currentCharacter) return;
  state.memories = await api('GET', '/api/characters/' + state.currentCharacter.id + '/memories');
  renderMemories();
}

function renderMemories() {
  const list = $('#mem-list');
  list.innerHTML = '';
  if (state.memories.length === 0) {
    list.innerHTML = '<div style="color:var(--text-dim);font-size:12px;">还没有记忆。手动添加，或点上方按钮从对话自动总结。</div>';
    return;
  }
  state.memories.forEach((m) => {
    const el = document.createElement('div');
    el.className = 'mem-item';
    el.innerHTML = `
      <textarea class="txt" rows="2">${escapeHTML(m.content)}</textarea>
      <div class="acts">
        <button class="mini-btn" data-act="save">保存</button>
        <button class="mini-btn" data-act="del">删除</button>
      </div>`;
    el.querySelector('[data-act="save"]').addEventListener('click', async () => {
      const v = el.querySelector('textarea').value.trim();
      try { await api('PUT', '/api/memories/' + m.id, { content: v }); toast('已保存'); }
      catch (e) { toast('保存失败：' + e.message); }
    });
    el.querySelector('[data-act="del"]').addEventListener('click', async () => {
      try { await api('DELETE', '/api/memories/' + m.id); await loadMemories(); }
      catch (e) { toast('删除失败：' + e.message); }
    });
    list.appendChild(el);
  });
}

$('#btn-add-mem').addEventListener('click', async () => {
  const ta = $('#mem-input');
  const v = ta.value.trim();
  if (!v || !state.currentCharacter) return;
  try {
    await api('POST', '/api/characters/' + state.currentCharacter.id + '/memories', { content: v });
    ta.value = '';
    await loadMemories();
    toast('记忆已添加');
  } catch (e) { toast('添加失败：' + e.message); }
});

$('#btn-auto-mem').addEventListener('click', async () => {
  if (!state.currentConv) return;
  const btn = $('#btn-auto-mem');
  btn.disabled = true; btn.textContent = '✨ 总结中…';
  try {
    const r = await api('POST', '/api/conversations/' + state.currentConv.id + '/summarize', { rounds: 20 });
    await loadMemories();
    toast(r.added && r.added.length ? `已总结 ${r.added.length} 条记忆` : '没有可总结的新内容');
  } catch (e) { toast('总结失败：' + e.message); }
  finally { btn.disabled = false; btn.textContent = '✨ 从最近对话自动总结为记忆'; }
});

/* =====================================================================
 * 设置面板
 * ===================================================================== */
$('#btn-settings').addEventListener('click', async () => {
  const c = state.config;
  $('#cfg-api_base').value = c.api_base || '';
  $('#cfg-api_key').value = c.api_key || '';
  $('#cfg-model').value = c.model || '';
  $('#cfg-temperature').value = c.temperature ?? 0.9;
  $('#val-temp').textContent = c.temperature ?? 0.9;
  $('#cfg-max_tokens').value = c.max_tokens ?? 512;
  $('#val-tokens').textContent = c.max_tokens ?? 512;
  $('#cfg-context_rounds').value = c.context_rounds ?? 30;
  $('#val-rounds').textContent = c.context_rounds ?? 30;
  $('#cfg-system_note').value = c.system_note || '';
  $('#cfg-image_api_base').value = c.image_api_base || '';
  $('#cfg-image_api_key').value = c.image_api_key || '';
  $('#cfg-image_model').value = c.image_model || 'dall-e-3';
  $('#cfg-image_size').value = c.image_size || '1024x1024';

  // 管理员才显示用户管理区（整张卡片显隐）
  const userSection = document.querySelectorAll('.user-section');
  if (state.isAdmin) {
    userSection.forEach((el) => el.classList.remove('hidden'));
    await loadUserList();
  } else {
    userSection.forEach((el) => el.classList.add('hidden'));
  }
  openModal('settings-modal');
});

['cfg-temperature', 'cfg-max_tokens', 'cfg-context_rounds'].forEach((id) => {
  const map = { 'cfg-temperature': 'val-temp', 'cfg-max_tokens': 'val-tokens', 'cfg-context_rounds': 'val-rounds' };
  $('#' + id).addEventListener('input', (e) => {
    $('#' + map[id]).textContent = e.target.value;
  });
});

$('#btn-save-config').addEventListener('click', async () => {
  const patch = {
    api_base: $('#cfg-api_base').value.trim(),
    api_key: $('#cfg-api_key').value.trim(),
    model: $('#cfg-model').value.trim(),
    temperature: parseFloat($('#cfg-temperature').value),
    max_tokens: parseInt($('#cfg-max_tokens').value, 10),
    context_rounds: parseInt($('#cfg-context_rounds').value, 10),
    system_note: $('#cfg-system_note').value,
    image_api_base: $('#cfg-image_api_base').value.trim(),
    image_api_key: $('#cfg-image_api_key').value.trim(),
    image_model: $('#cfg-image_model').value.trim() || 'dall-e-3',
    image_size: $('#cfg-image_size').value.trim() || '1024x1024',
  };
  try {
    state.config = await api('PUT', '/api/config', patch);
    applyTheme(state.config.theme);
    closeModals();
    toast('设置已保存');
  } catch (e) { toast('保存失败：' + e.message); }
});

async function runModelTest(type, btnId) {
  const btn = $('#' + btnId);
  const originalText = btn.textContent;
  btn.disabled = true; btn.textContent = '测试中…';
  try {
    const payload = { type };
    if (type === 'chat' || type === 'all') {
      payload.api_base = $('#cfg-api_base').value.trim();
      payload.api_key = $('#cfg-api_key').value.trim();
      payload.model = $('#cfg-model').value.trim();
    }
    if (type === 'image' || type === 'all') {
      payload.image_api_base = $('#cfg-image_api_base').value.trim();
      payload.image_api_key = $('#cfg-image_api_key').value.trim();
      payload.image_model = $('#cfg-image_model').value.trim();
    }
    const r = await api('POST', '/api/test', payload);
    if (type === 'chat' && r.chat) {
      toast(r.chat.ok ? '✅ 对话模型：' + (r.chat.sample || '连接正常') : '❌ 对话模型：' + r.chat.message);
    } else if (type === 'image' && r.image) {
      toast(r.image.ok ? '✅ 图像模型：' + r.image.message : '❌ 图像模型：' + r.image.message);
    } else {
      toast(r.ok ? '✅ 配置可用' : '❌ ' + (r.message || '配置不可用'));
    }
  } catch (e) { toast('测试失败：' + e.message); }
  finally { btn.disabled = false; btn.textContent = originalText; }
}

$('#btn-test-chat').addEventListener('click', () => runModelTest('chat', 'btn-test-chat'));
$('#btn-test-image').addEventListener('click', () => runModelTest('image', 'btn-test-image'));

/* =====================================================================
 * 用户管理（仅管理员可见）
 * ===================================================================== */
async function loadUserList() {
  if (!state.isAdmin) return;
  try {
    const users = await api('GET', '/api/users');
    const list = $('#user-list');
    list.innerHTML = '';
    if (!users.length) { list.innerHTML = '<div class="muted">暂无用户</div>'; return; }
    users.forEach((u) => {
      const el = document.createElement('div');
      el.className = 'user-item';
      const isAdmin = u.username === 'admin';
      el.innerHTML = `
        <div><b>${escapeHTML(u.username)}</b>${isAdmin ? ' <span class="tag">管理员</span>' : ''}</div>
        ${isAdmin ? '' : '<button class="btn danger small" data-uid="' + u.id + '">删除</button>'}
      `;
      const delBtn = el.querySelector('button[data-uid]');
      if (delBtn) {
        delBtn.addEventListener('click', async () => {
          if (!confirm('确定删除用户 ' + u.username + ' 吗？')) return;
          try {
            await api('DELETE', '/api/users/' + delBtn.getAttribute('data-uid'));
            await loadUserList();
            toast('用户已删除');
          } catch (e) { toast('删除失败：' + e.message); }
        });
      }
      list.appendChild(el);
    });
  } catch (e) { toast('加载用户列表失败：' + e.message); }
}

$('#btn-add-user').addEventListener('click', async () => {
  const u = $('#new-username').value.trim();
  const p = $('#new-password').value;
  if (!u || !p) { toast('请输入用户名和密码'); return; }
  if (p.length < 4) { toast('密码至少 4 位'); return; }
  try {
    await api('POST', '/api/users', { username: u, password: p });
    $('#new-username').value = '';
    $('#new-password').value = '';
    await loadUserList();
    toast('用户已添加');
  } catch (e) { toast('添加失败：' + e.message); }
});

$('#btn-change-pwd').addEventListener('click', async () => {
  const oldPwd = $('#pwd-old').value;
  const newPwd = $('#pwd-new').value;
  if (!newPwd || newPwd.length < 4) { toast('新密码至少 4 位'); return; }
  try {
    await api('PUT', '/api/users/me/password', {
      old_password: oldPwd || undefined,
      new_password: newPwd,
    });
    $('#pwd-old').value = '';
    $('#pwd-new').value = '';
    toast('密码已修改，请牢记新密码');
  } catch (e) { toast('修改失败：' + e.message); }
});

/* =====================================================================
 * PWA 注册（手机「添加到主屏幕」即可像 App 安装）
 * ===================================================================== */
function registerSW() {
  if (!('serviceWorker' in navigator)) return;
  navigator.serviceWorker.register('sw.js')
    .then((reg) => {
      // 发现新版 Service Worker 时立即切换，避免旧缓存导致登录屏不显示
      reg.addEventListener('updatefound', () => {
        const newWorker = reg.installing;
        if (!newWorker) return;
        newWorker.addEventListener('statechange', () => {
          if (newWorker.state === 'installed' && navigator.serviceWorker.controller) {
            newWorker.postMessage({ type: 'SKIP_WAITING' });
            toast('检测到新版，正在刷新…');
            setTimeout(() => location.reload(), 800);
          }
        });
      });
    })
    .catch(() => {});
}

init();
