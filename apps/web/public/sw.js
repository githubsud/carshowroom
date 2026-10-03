/*
 * SayyaraDMS service worker (BACKLOG 9.6, D-120). Registered in production builds only.
 *
 * - App shell: cache-first for the built files, so the app opens offline.
 * - API reads (GET /api/v1/...): network first, the last answer kept per user
 *   and URL so lists and records can be read offline. Writes are never cached
 *   or queued: offline, the app refuses them (the interceptor) and shows a banner.
 * - A new deployment ships a new CACHE name; old caches are removed on activate.
 */
const CACHE = 'sayyara-v1';
const API_CACHE = 'sayyara-api-v1';
const SHELL = ['/', '/index.html', '/manifest.webmanifest', '/icons/icon-192.png', '/icons/icon-512.png'];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE && k !== API_CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

/** The cache key of an API read includes the tenant, so showrooms never mix. */
function apiKey(request) {
  const url = new URL(request.url);
  url.searchParams.set('__tenant', request.headers.get('X-Tenant-Id') || '');
  return url.toString();
}

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') {
    return;
  }
  const url = new URL(request.url);

  if (url.pathname.startsWith('/api/v1/')) {
    // Signed URLs, files and the session are never cached.
    if (url.pathname.endsWith('/me') || url.searchParams.has('format')) {
      return;
    }
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response.ok) {
            const copy = response.clone();
            caches.open(API_CACHE).then((cache) => cache.put(apiKey(request), copy));
          }
          return response;
        })
        .catch(() =>
          caches.match(apiKey(request)).then((cached) => cached || Response.error()),
        ),
    );
    return;
  }

  if (url.origin !== self.location.origin) {
    return;
  }
  // Navigation: the app shell (Angular routes are client-side).
  if (request.mode === 'navigate') {
    event.respondWith(fetch(request).catch(() => caches.match('/index.html')));
    return;
  }
  event.respondWith(
    caches.match(request).then(
      (cached) =>
        cached ||
        fetch(request).then((response) => {
          if (response.ok && (url.pathname.endsWith('.js') || url.pathname.endsWith('.css') || url.pathname.startsWith('/i18n/'))) {
            const copy = response.clone();
            caches.open(CACHE).then((cache) => cache.put(request, copy));
          }
          return response;
        }),
    ),
  );
});

/** Sign-out clears every cached answer of this browser. */
self.addEventListener('message', (event) => {
  if (event.data === 'clear-api-cache') {
    event.waitUntil(caches.delete(API_CACHE));
  }
});
