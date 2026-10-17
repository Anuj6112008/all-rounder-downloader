/* IGDesk Downloader — service worker (app-shell cache).
   Strategy:
   - Static assets: cache-first with background refresh (fast repeat loads).
   - Navigation: network-first with cache fallback (works offline after 1st visit).
   - /api/*: NEVER cached (freshness + privacy; no user data stored).
*/
const CACHE = "igdesk-v1";
const SHELL = [
  "/",
  "/index.html",
  "/styles.css",
  "/app.js",
  "/sw-register.js",
  "/manifest.webmanifest",
  "/icons/favicon.svg",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
  "/about.html", "/faq.html", "/terms.html", "/privacy.html", "/dmca.html",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);

  // Never intercept or cache API calls.
  if (url.pathname.startsWith("/api/")) return;
  if (req.method !== "GET") return;

  if (req.mode === "navigate") {
    event.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put("/index.html", copy));
          return res;
        })
        .catch(() => caches.match("/index.html"))
    );
    return;
  }

  event.respondWith(
    caches.match(req).then((cached) => {
      const network = fetch(req)
        .then((res) => {
          if (res && res.status === 200 && res.type === "basic") {
            const copy = res.clone();
            caches.open(CACHE).then((c) => c.put(req, copy));
          }
          return res;
        })
        .catch(() => cached);
      return cached || network;
    })
  );
});
