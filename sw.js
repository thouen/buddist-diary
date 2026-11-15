/* 学佛日记 · 离线缓存
   ⚠️ 发布须知：每次发布新的 index.html，必须把下面 CACHE 的版本号 +1
   （例如 v25 → v26），否则老用户会一直读到缓存里的旧页面。
   发布检查清单见 README 的「发布检查清单」一节。 */
var CACHE = 'xuefo-diary-v45';
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
      /* 逐个 add：某个资源 404 不该让整个 install 失败，
         否则新版本永远装不上，用户就一直停在旧缓存里 */
      return Promise.all(ASSETS.map(function (u) {
        return c.add(u).catch(function () { });
      }));
    }).then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener('activate', function (e) {
  e.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(keys.map(function (k) {
        /* 只清本应用的缓存：同源下可能有别的 PWA，不能把它们的离线资源一起删掉 */
        return (k.indexOf('xuefo-diary-') === 0 && k !== CACHE) ? caches.delete(k) : null;
      }));
    }).then(function () { return self.clients.claim(); })
  );
});

self.addEventListener('fetch', function (e) {
  if (e.request.method !== 'GET') return;
  var req = e.request;
  e.respondWith(
    caches.match(req, { ignoreSearch: req.mode === 'navigate' }).then(function (hit) {
      if (hit) return hit;
      return fetch(req).then(function (res) {
        /* 只缓存同源且成功的响应：以前不看状态码，一次 404 会被缓存到
           下次改版本号为止，页面上就是「资源一直在坏」 */
        if (res && res.ok && res.type === 'basic') {
          var copy = res.clone();
          caches.open(CACHE).then(function (c) {
            c.put(req, copy).catch(function () { });
          }).catch(function () { });
        }
        return res;
      }).catch(function () {
        /* 离线：只有导航请求回首页兜底；图片等其它资源直接失败，
           别拿一份 HTML 冒充图片（老写法对任何 GET 都返回 index.html） */
        if (req.mode === 'navigate') return caches.match('./index.html');
        return Response.error();
      });
    })
  );
});
