'use strict';

const CACHE_PREFIX = 'rival-pwa-';
const CACHE_NAME = 'rival-pwa-static-v1';
const ATTENDANCE_CACHE_PREFIX = 'rival-attendance-shell-';
const ATTENDANCE_CACHE_NAME = 'rival-attendance-shell-v1';
const ATTENDANCE_SHELL_URLS = [
  '/static/attendance_offline.html',
  '/static/js/attendance_offline.js',
];
const CACHEABLE_PATHS = new Set([
  '/manifest.webmanifest',
  '/static/icon-192.png',
  '/static/icon-512.png',
  '/static/icon-maskable-512.png',
  '/static/apple-touch-icon.png',
  '/static/logo.png',
  '/static/Rival%20logo.jpg',
  '/static/manifest.webmanifest',
  '/static/js/ui-enhancements.js',
]);

function isCacheableStaticRequest(request) {
  if (request.method !== 'GET') {
    return false;
  }

  const url = new URL(request.url);
  return url.origin === self.location.origin && CACHEABLE_PATHS.has(url.pathname);
}

self.addEventListener('install', (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(ATTENDANCE_CACHE_NAME);
    await cache.addAll(ATTENDANCE_SHELL_URLS);
    await self.skipWaiting();
  })());
});

self.addEventListener('fetch', (event) => {
  const { request } = event;

  if (request.method !== 'GET') {
    return;
  }

  if (request.mode === 'navigate') {
    const url = new URL(request.url);
    if (url.origin === self.location.origin && url.pathname === '/attendance_table') {
      event.respondWith(fetch(request).catch(async () => {
        const cache = await caches.open(ATTENDANCE_CACHE_NAME);
        return cache.match('/static/attendance_offline.html');
      }));
      return;
    }
    event.respondWith(fetch(request));
    return;
  }

  if (!isCacheableStaticRequest(request)) {
    event.respondWith(fetch(request));
    return;
  }

  event.respondWith((async () => {
    const cache = await caches.open(CACHE_NAME);
    const cached = await cache.match(request);
    if (cached) {
      return cached;
    }

    const response = await fetch(request);
    if (response && response.ok) {
      await cache.put(request, response.clone());
    }
    return response;
  })());
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
      const cacheNames = await caches.keys();
      await Promise.all(
        cacheNames
        .filter((cacheName) => (
          (cacheName.startsWith(CACHE_PREFIX) && cacheName !== CACHE_NAME) ||
          (cacheName.startsWith(ATTENDANCE_CACHE_PREFIX) && cacheName !== ATTENDANCE_CACHE_NAME)
        ))
        .map((cacheName) => caches.delete(cacheName))
    );
    await self.clients.claim();
  })());
});
