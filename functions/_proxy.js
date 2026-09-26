/**
 * Cloudflare Pages Functions - Reverse Proxy
 * Discovers the live phone tunnel URL from endpoint.json on GitHub,
 * then forwards every request to it. No API keys needed by callers.
 */

const GITHUB_ENDPOINT_URL = "https://raw.githubusercontent.com/Beeta-inc/ntamediaserver/main/endpoint.json";
const DEFAULT_FALLBACK_ORIGIN = "https://placeholder.trycloudflare.com";

let cachedOrigin = null;
let lastFetchTime = 0;
const CACHE_TTL_MS = 10000; // re-check GitHub every 10s

export const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS, HEAD, PATCH",
  "Access-Control-Allow-Headers": "Content-Type, Authorization, Range, *",
  "Access-Control-Expose-Headers": "Accept-Ranges, Content-Range, Content-Length, Content-Type, *",
  "Access-Control-Max-Age": "86400"
};

export function setLiveOrigin(newOrigin) {
  if (newOrigin && newOrigin.startsWith("https://")) {
    cachedOrigin = newOrigin.replace(/\/+$/, "");
    lastFetchTime = Date.now();
  }
}

export async function getLiveOrigin(forceRefresh = false) {
  const now = Date.now();
  if (!forceRefresh && cachedOrigin && (now - lastFetchTime < CACHE_TTL_MS)) {
    return cachedOrigin;
  }

  try {
    const res = await fetch(`${GITHUB_ENDPOINT_URL}?_t=${now}`, {
      headers: { "Cache-Control": "no-cache, no-store" }
    });
    if (res.ok) {
      const data = await res.json();
      if (data && data.endpoint && data.endpoint.startsWith("https://")) {
        cachedOrigin = data.endpoint.replace(/\/+$/, "");
        lastFetchTime = now;
        return cachedOrigin;
      }
    }
  } catch (_) {}

  return cachedOrigin || DEFAULT_FALLBACK_ORIGIN;
}

export async function handleOptions() {
  return new Response(null, { status: 204, headers: CORS_HEADERS });
}

export async function handleRequest(context) {
  const { request } = context;

  if (request.method === "OPTIONS") return handleOptions();

  const url = new URL(request.url);
  let origin = await getLiveOrigin(false);
  let targetUrl = `${origin}${url.pathname}${url.search}`;

  let reqBody = undefined;
  if (!["GET", "HEAD"].includes(request.method)) {
    try { reqBody = await request.arrayBuffer(); } catch (_) { reqBody = request.body; }
  }

  let response = null;
  for (let attempt = 1; attempt <= 3; attempt++) {
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 30000);

      const proxyHeaders = new Headers(request.headers);
      proxyHeaders.delete("cf-connecting-ip");
      proxyHeaders.delete("cf-ray");
      proxyHeaders.delete("cf-ipcountry");
      proxyHeaders.delete("cf-visitor");
      try { proxyHeaders.set("Host", new URL(targetUrl).host); } catch (_) {}

      response = await fetch(new Request(targetUrl, {
        method: request.method,
        headers: proxyHeaders,
        body: reqBody instanceof ArrayBuffer ? reqBody.slice(0) : reqBody,
        redirect: "follow",
        signal: controller.signal
      }));
      clearTimeout(timeoutId);

      if ([502, 503, 504, 530].includes(response.status) && attempt < 3) {
        cachedOrigin = null;
        await new Promise(r => setTimeout(r, attempt * 200));
        origin = await getLiveOrigin(true);
        targetUrl = `${origin}${url.pathname}${url.search}`;
        continue;
      }
      break;
    } catch (_) {
      if (attempt < 3) {
        cachedOrigin = null;
        await new Promise(r => setTimeout(r, attempt * 200));
        origin = await getLiveOrigin(true);
        targetUrl = `${origin}${url.pathname}${url.search}`;
      }
    }
  }

  if (!response || [502, 503, 504, 530].includes(response.status)) {
    return new Response(JSON.stringify({ status: "reconnecting", retry_after_sec: 3 }), {
      status: 503,
      headers: { ...CORS_HEADERS, "Content-Type": "application/json", "Retry-After": "3" }
    });
  }

  const respHeaders = new Headers(response.headers);
  Object.entries(CORS_HEADERS).forEach(([k, v]) => respHeaders.set(k, v));

  return new Response(request.method === "HEAD" ? null : response.body, {
    status: response.status,
    statusText: response.statusText,
    headers: respHeaders
  });
}
