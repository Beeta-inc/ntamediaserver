import { CORS_HEADERS, setLiveOrigin, getLiveOrigin, handleOptions } from "./_proxy.js";

export const onRequestOptions = handleOptions;

// Phone calls POST /register_tunnel with { endpoint, secret } to register its live URL
export async function onRequestPost(context) {
  try {
    const data = await context.request.json();
    if (data && data.endpoint && data.secret === "ntamedia_tunnel_key") {
      const origin = data.endpoint.replace(/\/+$/, "");
      setLiveOrigin(origin);
      return new Response(JSON.stringify({
        status: "registered",
        active_origin: origin,
        timestamp: Math.floor(Date.now() / 1000)
      }), {
        status: 200,
        headers: { ...CORS_HEADERS, "Content-Type": "application/json" }
      });
    }
  } catch (_) {}

  return new Response(JSON.stringify({ status: "invalid_payload" }), {
    status: 400,
    headers: { ...CORS_HEADERS, "Content-Type": "application/json" }
  });
}

// GET /register_tunnel — returns current active origin
export async function onRequestGet(context) {
  const origin = await getLiveOrigin(false);
  return new Response(JSON.stringify({
    status: "ok",
    active_origin: origin,
    timestamp: Math.floor(Date.now() / 1000)
  }), {
    status: 200,
    headers: { ...CORS_HEADERS, "Content-Type": "application/json" }
  });
}
