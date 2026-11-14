/* 学佛日记 · 离线缓存
   ⚠️ 发布须知：每次发布新的 index.html，必须把下面 CACHE 的版本号 +1
   （例如 v25 → v26），否则老用户会一直读到缓存里的旧页面。
   发布检查清单见 README 的「发布检查清单」一节。 */
var CACHE = 'xuefo-diary-v34';
var ASSETS = [
  './',
  './index.html',
  './manifest.webmanifest',
  './icons/icon-192.png',
  './icons/icon-512.png',
  './icons/icon-maskable-512.png'
];

self.addEventListener('install', function (e) {
  e.waitUntil(
    caches.open(CACHE).then(function (c) {
      return c.addAll(ASSETS);
    }).then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener('activate', function (e) {
  e.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(keys.map(function (k) {
        return k === CACHE ? null : caches.delete(k);
      }));
    }).then(function () { return self.clients.claim(); })
  );
});

self.addEventListener('fetch', function (e) {
  if (e.request.method !== 'GET') return;
  e.respondWith(
    caches.match(e.request, { ignoreSearch: true }).then(function (hit) {
      if (hit) return hit;
      return fetch(e.request).then(function (res) {
        var copy = res.clone();
        caches.open(CACHE).then(function (c) {
          c.put(e.request, copy).catch(function () { });
        }).catch(function () { });
        return res;
      }).catch(function () {
        return caches.match('./index.html');
      });
    })
  );
});
