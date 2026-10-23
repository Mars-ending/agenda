/* 极简缓存：网络优先，断网回落。
   刻意不预缓存任何版本号 —— 免得“改了页面却看到旧的”。 */
const CACHE = 'agenda-v1';
const SHELL = ['/', '/manifest.json', '/icon-192.png'];

self.addEventListener('install', e => {
  self.skipWaiting();
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).catch(() => {}));
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(
    ks.filter(k => k !== CACHE).map(k => caches.delete(k))
  )).then(() => self.clients.claim()));
});

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;              // 同步请求绝不走缓存
  const url = new URL(req.url);
  if (url.pathname.startsWith('/sync') || url.pathname === '/health') return;
  e.respondWith(
    fetch(req).then(r => {
      const copy = r.clone();
      caches.open(CACHE).then(c => c.put(req, copy)).catch(() => {});
      return r;
    }).catch(() => caches.match(req).then(m => m || caches.match('/')))
  );
});
