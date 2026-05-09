self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open("notesnoop-static-v1").then((cache) =>
      cache.addAll(["/quick-capture", "/manifest.webmanifest", "/icon.svg", "/icon-192.png", "/icon-512.png"]),
    ),
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET" || !request.url.startsWith(self.location.origin)) return;
  event.respondWith(
    fetch(request).catch(() => caches.match(request).then((cached) => cached || caches.match("/quick-capture"))),
  );
});
