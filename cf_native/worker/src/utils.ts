export function json(data: unknown, init: ResponseInit = {}): Response {
  const headers = new Headers(init.headers);
  headers.set("content-type", "application/json; charset=utf-8");
  return new Response(JSON.stringify(data), { ...init, headers });
}

export function badRequest(message: string, extra: Record<string, unknown> = {}): Response {
  return json({ error: message, ...extra }, { status: 400 });
}

export function unauthorized(message = "Unauthorized"): Response {
  return json({ error: message }, { status: 401 });
}

export function notFound(message = "Not found"): Response {
  return json({ error: message }, { status: 404 });
}

export function nowMs(): number {
  return Date.now();
}

export function randomId(prefix: string): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  const hex = Array.from(bytes)
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
  return `${prefix}_${hex}`;
}

export function generateOtp(length = 6): string {
  const max = 10 ** length;
  const n = Math.floor(Math.random() * max);
  return String(n).padStart(length, "0");
}

export function normalizeToE164(phone: string | null | undefined): string | null {
  const raw = String(phone || "").trim();
  if (!raw) return null;

  const digits = raw.replace(/\D/g, "");
  if (raw.startsWith("+")) return digits ? `+${digits}` : null;

  if (digits.length === 10) return `+91${digits}`;
  if (digits.length >= 11 && digits.startsWith("91")) return `+${digits}`;
  return null;
}

export function parseCookies(cookieHeader: string | null): Record<string, string> {
  const out: Record<string, string> = {};
  if (!cookieHeader) return out;
  for (const part of cookieHeader.split(";")) {
    const idx = part.indexOf("=");
    if (idx === -1) continue;
    const k = part.slice(0, idx).trim();
    const v = part.slice(idx + 1).trim();
    if (k) out[k] = v;
  }
  return out;
}

export function setCookie(
  name: string,
  value: string,
  opts: { maxAgeSeconds?: number; httpOnly?: boolean; sameSite?: "Lax" | "Strict" | "None"; secure?: boolean; path?: string } = {},
): string {
  const parts: string[] = [`${name}=${value}`];
  parts.push(`Path=${opts.path || "/"}`);
  if (opts.maxAgeSeconds != null) parts.push(`Max-Age=${opts.maxAgeSeconds}`);
  if (opts.httpOnly !== false) parts.push("HttpOnly");
  parts.push(`SameSite=${opts.sameSite || "Lax"}`);
  if (opts.secure !== false) parts.push("Secure");
  return parts.join("; ");
}
