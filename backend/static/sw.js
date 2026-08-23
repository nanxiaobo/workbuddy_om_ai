/* service worker —— 仅缓存应用外壳，API 与流式接口一律走网络，避免破坏对话。
 *
 * 强制保证：
 *   - HTML（index.html / users.html）每次都网络优先，避免因 SW 缓存返回旧 DOM 导致用户看不到前端改动。
 *   - CSS / JS / icons：cache-first + 后台 revalidate（命中则秒开、未命中走网络）。
 *   - /api/*：永远走网络。
 *   - 版本号升级时（ai-chat-shell-vXX）自动清理所有旧 cache。
 */
const VERSION = 'v26';
const CACHE = 'ai-chat-shell-' + VERSION;   // 每次大版本更新请改 VERSION
const SHELL = [
  '/',
  '/index.html',
  '/users.html',
  '/css/style.css',
  '/js/shared.js',
  '/js/app.js',
  '/js/users.js',
  '/manifest.json',
  '/icons/icon-192.png',
  '/icons/icon-512.png',
];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (url.origin !== self.location.origin) return;        // 跨域跳过

  // API 与流式接口：始终走网络
  if (url.pathname.startsWith('/api')) return;

  // GET 之外的方法不缓存
  if (e.request.method !== 'GET') return;

  // HTML（含带 ?v= 缓存破坏后缀的 HTML）—— Network-first，避免读到旧 DOM
  const isHtml = (p) => p === '/' || p === '/index.html' || p === '/users.html' || p.endsWith('.html');
  if (isHtml(url.pathname)) {
    e.respondWith(
      fetch(e.request)
        .then((resp) => {
          // 后台更新缓存（避免离线场景下还能打开）
          const copy = resp.clone();
          caches.open(CACHE).then((c) => c.put(e.request, copy)).catch(() => {});
          return resp;
        })
        .catch(() => caches.match('/index.html'))
    );
    return;
  }

  // 静态资源（css/js/icons...）：cache-first + 后台 revalidate
  e.respondWith(
    caches.match(e.request).then((hit) => {
      if (hit) {
        fetch(e.request).then((resp) => {
          if (resp && resp.ok) {
            const copy = resp.clone();
            caches.open(CACHE).then((c) => c.put(e.request, copy)).catch(() => {});
          }
        }).catch(() => {});
        return hit;
      }
      return fetch(e.request).then((resp) => {
        const copy = resp.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy)).catch(() => {});
        return resp;
      }).catch(() => caches.match('/index.html'));
    })
  );
});

// 接收页面发来的「立即跳过等待」消息，确保新版第一时间生效
self.addEventListener('message', (e) => {
  if (e.data && e.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});
