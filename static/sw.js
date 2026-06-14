// LocusAI service worker — PWA install + Web Push notifications.
// Kept deliberately minimal: a network-first shell (no aggressive caching that
// could serve stale dashboards) plus push handling.

const VERSION = 'locusai-v1';

self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

// Network-first; only fall back to a tiny offline message for navigations.
self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  if (req.mode === 'navigate') {
    event.respondWith(
      fetch(req).catch(() =>
        new Response(
          '<h1 style="font-family:sans-serif;padding:2rem">You\'re offline</h1><p style="font-family:sans-serif;padding:0 2rem">LocusAI needs a connection. Reconnect and try again.</p>',
          { headers: { 'Content-Type': 'text/html' } }
        )
      )
    );
  }
});

// Incoming push -> show a notification.
self.addEventListener('push', (event) => {
  let data = { title: 'LocusAI', body: 'You have a new notification', url: '/dashboard' };
  try {
    if (event.data) data = Object.assign(data, event.data.json());
  } catch (e) { /* keep defaults */ }
  event.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      icon: '/static/logo.svg',
      badge: '/static/favicon.svg',
      data: { url: data.url || '/dashboard' },
      tag: data.tag || 'locusai',
    })
  );
});

// Tap a notification -> focus an existing tab or open the target URL.
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || '/dashboard';
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((list) => {
      for (const c of list) {
        if ('focus' in c) { c.navigate(url); return c.focus(); }
      }
      if (self.clients.openWindow) return self.clients.openWindow(url);
    })
  );
});
