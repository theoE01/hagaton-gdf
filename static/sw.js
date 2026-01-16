/* PWA Offline-first - Participa DF (MVP) */

const CACHE_NAME = "participa-df-v1";

// Rotas/páginas que você quer garantir offline (ajuste conforme suas rotas)
const CORE_ASSETS = [
  "/",                 // home
  "/admin/login",      // admin login (opcional)
  "/static/manifest.json",
  "/static/sw.js"
  // inclua aqui seus CSS/JS se forem arquivos separados
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(CORE_ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.map((k) => (k !== CACHE_NAME ? caches.delete(k) : null)))
    )
  );
  self.clients.claim();
});

// Estratégia:
// - Navegação (HTML): network-first (garante versão atual quando há internet)
// - Assets (css/js/images): cache-first
self.addEventListener("fetch", (event) => {
  const req = event.request;

  // Não interferir em POST (upload)
  if (req.method !== "GET") return;

  const url = new URL(req.url);

  // Somente para o mesmo domínio
  if (url.origin !== self.location.origin) return;

  // Navegação (páginas)
  const isNavigation = req.mode === "navigate" || (req.headers.get("accept") || "").includes("text/html");
  if (isNavigation) {
    event.respondWith(networkFirst(req));
    return;
  }

  // Assets
  event.respondWith(cacheFirst(req));
});

async function cacheFirst(req) {
  const cache = await caches.open(CACHE_NAME);
  const cached = await cache.match(req);
  if (cached) return cached;

  const fresh = await fetch(req);
  // Cacheia somente respostas ok
  if (fresh && fresh.ok) cache.put(req, fresh.clone());
  return fresh;
}

async function networkFirst(req) {
  const cache = await caches.open(CACHE_NAME);
  try {
    const fresh = await fetch(req);
    if (fresh && fresh.ok) cache.put(req, fresh.clone());
    return fresh;
  } catch (err) {
    const cached = await cache.match(req);
    // fallback: home cacheada
    return cached || (await cache.match("/"));
  }
}
