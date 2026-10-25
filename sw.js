/* ProofCheck static app shell only. Data, reports, and evidence ALWAYS use network. */
'use strict';
const CACHE = 'proofcheck-static-v3';
const SHELL = ['/', '/index.html', '/assets/app.js', '/assets/style.css', '/manifest.webmanifest', '/assets/icon-192.png', '/assets/icon-512.png'];
self.addEventListener('install', evt => { evt.waitUntil(caches.open(CACHE).then(c=>c.addAll(SHELL)).then(()=>self.skipWaiting())); });
self.addEventListener('activate', evt => { evt.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim())); });
self.addEventListener('fetch', evt => {
 const url = new URL(evt.request.url);
 if(evt.request.method !== 'GET' || url.origin !== self.location.origin || !SHELL.includes(url.pathname))return;
 // Network-first so deployed updates are picked up. A cached shell is not a usable offline service.
 evt.respondWith(fetch(evt.request).then(res=>{
  if(res.ok){const copy=res.clone();caches.open(CACHE).then(c=>c.put(evt.request,copy));}
  return res;
 }).catch(()=>caches.match(evt.request)));
});
