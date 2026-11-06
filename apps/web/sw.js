// 画面の部品だけをこの端末に置いておき、ネットが落ちても画面を開けるようにする。
// API の応答（生徒の問いや結果）は置かない。共用の端末に生徒のデータを残さないため。
const CACHE = "mushitori-shell-v1";
const SHELL = ["/", "/index.html", "/app.js", "/offline.js", "/style.css"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  const shell = SHELL.includes(url.pathname);
  if (event.request.method !== "GET" || url.origin !== self.location.origin || !shell) return;
  // つながっていれば常に新しいものを使い（更新がすぐ届く）、つながらないときだけ置いておいたものを出す
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        if (response.ok) {
          const copy = response.clone();
          caches.open(CACHE).then((cache) => cache.put(event.request, copy));
        }
        return response;
      })
      .catch(() => caches.match(event.request).then((hit) => hit || caches.match("/index.html"))),
  );
});
