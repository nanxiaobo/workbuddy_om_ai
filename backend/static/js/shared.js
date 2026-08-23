/* =====================================================================
 * shared.js —— 跨页面公共工具
 *   - $ / $$ 选择器
 *   - escapeHTML / avatarHTML
 *   - createApi(token) 工厂：根据传入 token 创建 fetch 封装
 *   - toast / setToken / getToken
 *
 * 用法（在页面脚本前以 <script src="/js/shared.js"></script> 引入）：
 *   const api = createApi(getToken());   // 单页面会话内复用
 * ===================================================================== */
'use strict';

window.$ = (sel) => document.querySelector(sel);
window.$$ = (sel) => Array.from(document.querySelectorAll(sel));

window.escapeHTML = function escapeHTML(s) {
  return String(s).replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
};

window.avatarHTML = function avatarHTML(avatar, cls = 'avatar') {
  if (avatar && (avatar.startsWith('data:image') || avatar.startsWith('http'))) {
    return `<div class="${cls}"><img src="${escapeHTML(avatar)}" alt=""></div>`;
  }
  return `<div class="${cls}">${escapeHTML(avatar || '🤖')}</div>`;
};

window.toast = function toast(msg) {
  const t = $('#toast');
  if (!t) return;
  t.textContent = msg;
  t.classList.remove('hidden');
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.add('hidden'), 2600);
};

/* 创建带 token 的 fetch 封装。
 *   - 401 时清空 token + showLogin + 抛错
 *   - 非 2xx 抛错（带 detail 字段）
 *   - 返回 JSON 或 Response
 */
window.createApi = function createApi(getTokenFn, showLoginFn) {
  return function api(method, path, body) {
    const opt = { method, headers: {} };
    const t = getTokenFn();
    if (t) opt.headers['Authorization'] = 'Bearer ' + t;
    if (body !== undefined) {
      opt.headers['Content-Type'] = 'application/json';
      opt.body = JSON.stringify(body);
    }
    return fetch(path, opt).then(async (r) => {
      if (r.status === 401) {
        if (showLoginFn) showLoginFn();
        throw new Error('登录已失效');
      }
      if (r.status === 403) {
        let msg = '没有权限';
        try { msg = (await r.clone().json()).detail || msg; } catch (e) {}
        throw new Error(msg);
      }
      if (!r.ok) {
        let msg = `请求失败 (${r.status})`;
        try { msg = (await r.json()).detail || msg; } catch (e) {}
        throw new Error(msg);
      }
      const ct = r.headers.get('content-type') || '';
      return ct.includes('application/json') ? r.json() : r;
    });
  };
};
