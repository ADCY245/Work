import { randomId } from "./utils";

export async function hashPassword(password: string, secret: string): Promise<string> {
  // PBKDF2 (built-in WebCrypto). Format: pbkdf2$<iters>$<saltB64>$<hashB64>
  const iters = 150_000;
  const salt = new TextEncoder().encode(randomId("salt"));

  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(`${password}:${secret}`),
    { name: "PBKDF2" },
    false,
    ["deriveBits"],
  );

  const bits = await crypto.subtle.deriveBits(
    { name: "PBKDF2", hash: "SHA-256", salt, iterations: iters },
    key,
    256,
  );

  const saltB64 = btoa(String.fromCharCode(...salt));
  const hashB64 = btoa(String.fromCharCode(...new Uint8Array(bits)));
  return `pbkdf2$${iters}$${saltB64}$${hashB64}`;
}

export async function verifyPassword(password: string, stored: string, secret: string): Promise<boolean> {
  const parts = stored.split("$");
  if (parts.length !== 4) return false;
  const [algo, itersRaw, saltB64, hashB64] = parts;
  if (algo !== "pbkdf2") return false;

  const iters = Number(itersRaw);
  if (!Number.isFinite(iters) || iters <= 0) return false;

  const salt = Uint8Array.from(atob(saltB64), (c) => c.charCodeAt(0));
  const expected = Uint8Array.from(atob(hashB64), (c) => c.charCodeAt(0));

  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(`${password}:${secret}`),
    { name: "PBKDF2" },
    false,
    ["deriveBits"],
  );

  const bits = await crypto.subtle.deriveBits(
    { name: "PBKDF2", hash: "SHA-256", salt, iterations: iters },
    key,
    expected.length * 8,
  );

  const got = new Uint8Array(bits);
  if (got.length !== expected.length) return false;
  let diff = 0;
  for (let i = 0; i < got.length; i++) diff |= got[i] ^ expected[i];
  return diff === 0;
}
