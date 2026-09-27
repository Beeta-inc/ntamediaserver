import { CORS_HEADERS, handleOptions } from "./_proxy.js";

export const onRequestOptions = handleOptions;

export async function onRequestGet(context) {
  const url = new URL(context.request.url);

  // 1. Try serving from local Pages ASSETS
  if (context.env && context.env.ASSETS) {
    try {
      const assetUrl = new URL("/docs.html", url.origin);
      const res = await context.env.ASSETS.fetch(assetUrl);
      if (res.ok) {
        const headers = new Headers(res.headers);
        Object.entries(CORS_HEADERS).forEach(([k, v]) => headers.set(k, v));
        headers.set("Content-Type", "text/html; charset=utf-8");
        return new Response(res.body, { status: 200, headers });
      }
    } catch (e) {}
  }

  // 2. Direct Raw GitHub fallback
  try {
    const ghRes = await fetch("https://raw.githubusercontent.com/Beeta-inc/ntamediaserver/main/docs.html");
    if (ghRes.ok) {
      const html = await ghRes.text();
      return new Response(html, {
        status: 200,
        headers: {
          ...CORS_HEADERS,
          "Content-Type": "text/html; charset=utf-8",
          "Cache-Control": "public, max-age=60"
        }
      });
    }
  } catch (e) {}

  return new Response("Documentation is synchronizing, please refresh in a moment.", {
    status: 200,
    headers: { ...CORS_HEADERS, "Content-Type": "text/plain" }
  });
}
