export interface Env {
  RENDER_ORIGIN: string;
}

const HOP_BY_HOP = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailers",
  "transfer-encoding",
  "upgrade",
]);

function stripHopByHop(headers: Headers): Headers {
  const out = new Headers();
  headers.forEach((v, k) => {
    if (!HOP_BY_HOP.has(k.toLowerCase())) out.set(k, v);
  });
  return out;
}

function joinOrigin(origin: string, url: URL): string {
  const o = origin.replace(/\/$/, "");
  const path = url.pathname + (url.search || "");
  return o + path;
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const origin = (env.RENDER_ORIGIN || "").trim();
    if (!origin) {
      return new Response("RENDER_ORIGIN is not configured", { status: 500 });
    }

    const incomingUrl = new URL(request.url);
    const upstreamUrl = joinOrigin(origin, incomingUrl);

    const headers = stripHopByHop(request.headers);

    // Ensure upstream sees correct host/proto
    headers.set("x-forwarded-host", incomingUrl.host);
    headers.set("x-forwarded-proto", incomingUrl.protocol.replace(":", ""));

    // Forward client IP if present
    const cfConnectingIp = request.headers.get("cf-connecting-ip");
    if (cfConnectingIp) headers.set("x-forwarded-for", cfConnectingIp);

    const init: RequestInit = {
      method: request.method,
      headers,
      redirect: "manual",
    };

    // Only forward a body for methods that support it
    if (request.method !== "GET" && request.method !== "HEAD") {
      init.body = request.body;
      (init as any).duplex = "half";
    }

    const upstreamRes = await fetch(upstreamUrl, init);

    const resHeaders = stripHopByHop(upstreamRes.headers);

    // Rewrite absolute redirects from Render -> Cloudflare Worker host
    const loc = resHeaders.get("location");
    if (loc) {
      try {
        const locUrl = new URL(loc, origin);
        const originUrl = new URL(origin);
        if (locUrl.origin === originUrl.origin) {
          locUrl.host = incomingUrl.host;
          locUrl.protocol = incomingUrl.protocol;
          resHeaders.set("location", locUrl.toString());
        }
      } catch {
        // ignore
      }
    }

    return new Response(upstreamRes.body, {
      status: upstreamRes.status,
      statusText: upstreamRes.statusText,
      headers: resHeaders,
    });
  },
};
