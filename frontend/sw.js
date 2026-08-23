/* service worker —— 仅缓存应用外壳，API 与流式接口一律走网络，避免破坏对话 */
const CACHE = 'ai-chat-shell-v12';          // 每次大版本更新请改版本号
const SHELL = [
  './',
  './index.html',
  './users.html',
  './style.css',
  './app.js',
  './manifest.json',
  './icons/icon-192.png',
  './icons/icon-512.png',
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
  // API 与流式接口：永远走网络，不缓存
  if (url.pathname.startsWith('/api')) {
    return; // 交给浏览器默认网络请求
  }
  // 其他静态资源：缓存优先，失败回退网络
  if (e.request.method !== 'GET') return;
  e.respondWith(
    caches.match(e.request).then((hit) =>
      hit || fetch(e.request).then((resp) => {
        const copy = resp.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy)).catch(() => {});
        return resp;
      }).catch(() => caches.match('./index.html'))
    )
  );
});

// 接收页面发来的「立即跳过等待」消息，确保新版第一时间生效
self.addEventListener('message', (e) => {
  if (e.data && e.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});
