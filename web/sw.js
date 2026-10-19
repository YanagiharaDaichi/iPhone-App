// Offline support. The app shell is network-first (so updates arrive when online) with the
// cache as fallback; the versioned wllama files are cache-first. Model downloads from
// Hugging Face are cross-origin and left alone: wllama stores those in OPFS itself.

const VERSION = '1.0.0';
const SHELL_CACHE = `shell-${VERSION}`;
const VENDOR_CACHE = 'vendor-wllama-3.8.1';

const SHELL = [
  './',
  './index.html',
  './app.css',
  './js/app.js',
  './js/engine.js',
  './js/markdown.js',
  './js/models.js',
  './manifest.webmanifest',
  './icons/icon-192.png',
  './icons/icon-512.png',
  './icons/apple-touch-icon.png',
];

function vendorFiles() {
  // Safari (no JSPI / wasm64) only ever uses the compat build; skip the other 9MB.
  let memory64 = false;
  try {
    new WebAssembly.Memory({ address: 'i64', initial: 1n });
    memory64 = true;
  } catch {}
  const compat = !('Suspending' in WebAssembly) || !memory64;
  return [
    './vendor/wllama-3.8.1/index.js',
    ...(compat
      ? ['./vendor/wllama-compat-3.8.1/wllama.js', './vendor/wllama-compat-3.8.1/wllama.wasm']
      : ['./vendor/wllama-3.8.1/wllama.wasm']),
  ];
}

self.addEventListener('install', (event) => {
  event.waitUntil(
    (async () => {
      const shell = await caches.open(SHELL_CACHE);
      await shell.addAll(SHELL.map((path) => new Request(path, { cache: 'reload' })));
      const vendor = await caches.open(VENDOR_CACHE);
      for (const path of vendorFiles()) {
        if (!(await vendor.match(path))) await vendor.add(path);
      }
      await self.skipWaiting();
    })(),
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      const keep = new Set([SHELL_CACHE, VENDOR_CACHE]);
      for (const key of await caches.keys()) {
        if (!keep.has(key)) await caches.delete(key);
      }
      await self.clients.claim();
    })(),
  );
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);
  if (request.method !== 'GET' || url.origin !== self.location.origin) return;

  if (url.pathname.includes('/vendor/')) {
    event.respondWith(cacheFirst(request, VENDOR_CACHE));
  } else {
    event.respondWith(networkFirst(request, SHELL_CACHE));
  }
});

async function cacheFirst(request, cacheName) {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(request, { ignoreSearch: true });
  if (cached) return cached;
  const response = await fetch(request);
  if (response.ok) await cache.put(request, response.clone());
  return response;
}

async function networkFirst(request, cacheName) {
  const cache = await caches.open(cacheName);
  try {
    const response = await withTimeout(fetch(request, { cache: 'no-cache' }), 4000);
    if (response.ok) {
      await cache.put(request, response.clone());
      return response;
    }
    return (await cache.match(request, { ignoreSearch: true })) ?? response;
  } catch {
    const cached =
      (await cache.match(request, { ignoreSearch: true })) ??
      (request.mode === 'navigate' ? await cache.match('./index.html') : undefined);
    if (cached) return cached;
    return new Response('オフラインです。', { status: 503, headers: { 'Content-Type': 'text/plain; charset=utf-8' } });
  }
}

function withTimeout(promise, ms) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('timeout')), ms);
    promise.then(
      (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      (error) => {
        clearTimeout(timer);
        reject(error);
      },
    );
  });
}
