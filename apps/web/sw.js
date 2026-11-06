// 画面の部品だけをこの端末に置いておき、すぐに開けるようにする。ネットが落ちても画面は開ける。
// API の応答（生徒の問いや結果）は置かない。共用の端末に生徒のデータを残さないため。
//
// 置いてあるものをすぐに返し（立ち上がりを待たせない）、裏で新しいものを取りに行って置き換える。
// 中身が変わっていたら画面に知らせ、再読み込みで新しい版にしてもらう。
const CACHE = "mushitori-shell-v2";
const SHELL = ["/", "/index.html", "/app.js", "/offline.js", "/style.css"];
// Firebase Hosting の設定（公開してよい値）。手元の開発には無いので、取れたときだけ置く
const OPTIONAL = ["/__/firebase/init.json"];

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

async function notifyUpdated() {
  const clients = await self.clients.matchAll({ type: "window" });
  for (const client of clients) client.postMessage({ type: "shell-updated" });
}

async function refresh(cache, request, cached) {
  // ブラウザの HTTP キャッシュを素通りさせず、必ず配信元に新しいものがあるかを確かめる
  const response = await fetch(request, { cache: "no-cache" });
  if (response.ok) {
    await cache.put(request, response.clone());
    const before = cached?.headers.get("etag");
    const after = response.headers.get("etag");
    if (before && after && before !== after) await notifyUpdated();
  }
  return response;
}

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  const cacheable = SHELL.includes(url.pathname) || OPTIONAL.includes(url.pathname);
  if (event.request.method !== "GET" || url.origin !== self.location.origin || !cacheable) return;
  const work = caches.open(CACHE).then(async (cache) => {
    const cached = await cache.match(event.request);
    return { cache, cached, network: refresh(cache, event.request, cached) };
  });
  // 置いてあるものをすぐに返す。無ければネットから取り、取れなければ置いてある画面を出す
  event.respondWith(work.then(({ cache, cached, network }) => cached || network.catch(() => cache.match("/index.html"))));
  // 新しいものは裏で取り、次に開いたときに使う
  event.waitUntil(work.then(({ network }) => network.catch(() => {})));
});
