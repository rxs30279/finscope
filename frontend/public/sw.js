// Minimal service worker. Its only job is to satisfy the browser's PWA install
// criteria — Chrome/Edge won't fire `beforeinstallprompt` (and won't show the
// address-bar install icon) unless an active service worker with a fetch
// handler controls the page. It deliberately caches nothing: every request
// goes straight to the network, so there's no stale-asset risk and nothing to
// invalidate on deploy.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));
// A fetch listener must exist for installability; not calling respondWith lets
// the browser handle every request normally (online-only, no caching).
self.addEventListener("fetch", () => {});
