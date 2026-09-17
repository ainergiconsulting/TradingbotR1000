const CACHE_VERSION = "tradingbot-r1000-20260916g4";
self.addEventListener("install", event => { self.skipWaiting(); });
self.addEventListener("activate", event => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter(k => k !== CACHE_VERSION).map(k => caches.delete(k)));
    await self.clients.claim();
  })());
});
self.addEventListener("fetch", event => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin === self.location.origin && (url.pathname === "/" || url.pathname.endsWith("/app.js") || url.pathname.endsWith("/app.css") || url.pathname === "/manifest.webmanifest")) {
    event.respondWith(fetch(request, {cache: "no-store"}).catch(() => caches.match(request)));
  }
});
