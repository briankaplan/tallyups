// Service Worker for Tallyups PWA - v4
const CACHE_NAME = 'tallyups-v4';
const STATIC_CACHE = 'tallyups-static-v4';
const DYNAMIC_CACHE = 'tallyups-dynamic-v4';
const OFFLINE_QUEUE = 'tallyups-offline-queue';

// Core app shell to cache
const APP_SHELL = [
  '/scanner',
  '/contacts',
  '/manifest.json',
  '/receipt-icon-192.png',
  '/receipt-icon-512.png'
];

// Install - cache app shell
self.addEventListener('install', (event) => {
  console.log('[SW] Installing service worker v2...');
  event.waitUntil(
    caches.open(STATIC_CACHE)
      .then((cache) => {
        console.log('[SW] Caching app shell');
        return cache.addAll(APP_SHELL).catch(err => {
          console.log('[SW] Some resources failed to cache:', err);
        });
      })
  );
  self.skipWaiting();
});

// Activate - clean old caches
self.addEventListener('activate', (event) => {
  console.log('[SW] Activating service worker v2...');
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames.map((cacheName) => {
          if (cacheName !== STATIC_CACHE && cacheName !== DYNAMIC_CACHE) {
            console.log('[SW] Deleting old cache:', cacheName);
            return caches.delete(cacheName);
          }
        })
      );
    })
  );
  self.clients.claim();
});

// Fetch - stale-while-revalidate for pages, cache-first for assets
self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // Skip non-GET and API requests
  if (request.method !== 'GET') {
    return;
  }

  // API requests - network only, queue if offline
  if (url.pathname.startsWith('/api/') ||
      url.pathname === '/mobile-upload' ||
      url.pathname === '/ocr' ||
      url.pathname === '/csv' ||
      url.pathname === '/health') {
    event.respondWith(networkOnly(request));
    return;
  }

  // Images - cache first
  if (request.destination === 'image') {
    event.respondWith(cacheFirst(request));
    return;
  }

  // HTML pages - stale while revalidate
  if (request.destination === 'document' || url.pathname === '/scanner') {
    event.respondWith(staleWhileRevalidate(request));
    return;
  }

  // Everything else - cache first with network fallback
  event.respondWith(cacheFirst(request));
});

// Cache strategies
async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) {
    return cached;
  }
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(DYNAMIC_CACHE);
      cache.put(request, response.clone());
    }
    return response;
  } catch (err) {
    return new Response('Offline', { status: 503 });
  }
}

async function staleWhileRevalidate(request) {
  const cached = await caches.match(request);

  const fetchPromise = fetch(request).then((response) => {
    if (response.ok) {
      const cache = caches.open(STATIC_CACHE);
      cache.then(c => c.put(request, response.clone()));
    }
    return response;
  }).catch(() => cached);

  return cached || fetchPromise;
}

async function networkOnly(request) {
  try {
    return await fetch(request);
  } catch (err) {
    return new Response(JSON.stringify({ error: 'offline', cached: false }), {
      status: 503,
      headers: { 'Content-Type': 'application/json' }
    });
  }
}

// Background sync for offline uploads
self.addEventListener('sync', (event) => {
  console.log('[SW] Background sync triggered:', event.tag);
  if (event.tag === 'receipt-upload') {
    event.waitUntil(syncPendingUploads());
  }
});

async function syncPendingUploads() {
  console.log('[SW] Syncing pending uploads...');
  // Notify all clients to sync
  const clients = await self.clients.matchAll();
  clients.forEach(client => {
    client.postMessage({ type: 'SYNC_UPLOADS' });
  });
}

// Push notifications (for future use)
self.addEventListener('push', (event) => {
  if (!event.data) return;

  const data = event.data.json();
  const options = {
    body: data.body || 'New notification',
    icon: '/receipt-icon-192.png',
    badge: '/receipt-icon-192.png',
    vibrate: [100, 50, 100],
    data: data.url || '/scanner',
    actions: [
      { action: 'open', title: 'Open' },
      { action: 'dismiss', title: 'Dismiss' }
    ]
  };

  event.waitUntil(
    self.registration.showNotification(data.title || 'Tallyups', options)
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  if (event.action === 'open' || !event.action) {
    event.waitUntil(
      clients.openWindow(event.notification.data || '/scanner')
    );
  }
});

// Message handling from main app
self.addEventListener('message', (event) => {
  if (event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
  if (event.data.type === 'CACHE_RECEIPT') {
    // Cache a receipt image for offline viewing
    caches.open(DYNAMIC_CACHE).then(cache => {
      cache.put(event.data.url, new Response(event.data.blob));
    });
  }
});
