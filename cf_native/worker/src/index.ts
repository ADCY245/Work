import type { Env } from "./types";
import { badRequest, json, nowMs, randomId, setCookie, generateOtp } from "./utils";
import { hashPassword, verifyPassword } from "./crypto";
import { send_email } from "./email";

const OTP_TTL_SECONDS = 60 * 10;
const SESSION_TTL_SECONDS = 60 * 60 * 24 * 3;

async function readJson<T>(req: Request): Promise<T | null> {
  try {
    return (await req.json()) as T;
  } catch {
    return null;
  }
}

function sessionCookieName(env: Env): string {
  return (env.SESSION_COOKIE_NAME || "physihome_session").trim() || "physihome_session";
}

function secret(env: Env): string {
  return (env.SECRET_KEY || "CHANGE_ME").trim() || "CHANGE_ME";
}

async function getUserFromSession(req: Request, env: Env): Promise<{ id: string; role: string } | null> {
  const cookies = parseCookies(req.headers.get("cookie"));
  const token = cookies[sessionCookieName(env)];
  if (!token) return null;

  const key = `sess:${token}`;
  const userId = await env.SESSION_KV.get(key);
  if (!userId) return null;

  const row = await env.DB.prepare("SELECT id, role FROM users WHERE id = ?")
    .bind(userId)
    .first<{ id: string; role: string }>();
  return row || null;
}

function withCors(req: Request, res: Response): Response {
  const origin = req.headers.get("origin") || "*";
  const headers = new Headers(res.headers);
  headers.set("access-control-allow-origin", origin);
  headers.set("access-control-allow-credentials", "true");
  headers.set("access-control-allow-headers", "content-type");
  headers.set("access-control-allow-methods", "GET,POST,OPTIONS");
  return new Response(res.body, { status: res.status, statusText: res.statusText, headers });
}

export default {
  async fetch(req: Request, env: Env): Promise<Response> {
    if (req.method === "OPTIONS") {
      return withCors(req, new Response(null, { status: 204 }));
    }

    const url = new URL(req.url);

    // Health
    if (url.pathname === "/api/health") {
      return withCors(req, json({ ok: true }));
    }

    // --- AUTH ---
    if (url.pathname === "/api/auth/signup" && req.method === "POST") {
      const body = await readJson<{ email: string; phone: string; password: string; first_name?: string; last_name?: string }>(req);
      if (!body) return withCors(req, badRequest("Invalid JSON"));

      const email = String(body.email || "").trim().toLowerCase();
      const phone = String(body.phone || "").trim();
      const password = String(body.password || "");
      if (!email || !phone || !password) return withCors(req, badRequest("Missing fields"));

      const existing = await env.DB.prepare("SELECT id FROM users WHERE email = ? OR phone = ?")
        .bind(email, phone)
        .first<{ id: string }>();
      if (existing) return withCors(req, badRequest("Account already exists"));

      const id = randomId("usr");
      const pwHash = await hashPassword(password, secret(env));
      const ts = nowMs();

      await env.DB.prepare(
        "INSERT INTO users (id, email, phone, first_name, last_name, role, password_hash, is_otp_verified, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'user', ?, 0, ?, ?)",
      )
        .bind(id, email, phone, body.first_name || "", body.last_name || "", pwHash, ts, ts)
        .run();

      // Send OTP
      const otp = generateOtp(6);
      await env.OTP_KV.put(`otp:${email}`, JSON.stringify({ otp, user_id: id, created_at: ts }), { expirationTtl: OTP_TTL_SECONDS });
      await _send_otp_email(env, email, otp);

      return withCors(req, json({ ok: true }));
    }

    if (url.pathname === "/api/auth/resend-otp" && req.method === "POST") {
      const body = await readJson<{ phone: string }>(req);
      if (!body) return withCors(req, badRequest("Invalid JSON"));
      const phone = String(body.phone || "").trim();
      if (!phone) return withCors(req, badRequest("Missing phone"));

      const user = await env.DB.prepare("SELECT id, email, is_otp_verified FROM users WHERE phone = ?").bind(phone).first<{ id: string; email: string; is_otp_verified: number }>();
      if (!user) return withCors(req, badRequest("Account not found"));
      if (user.is_otp_verified) return withCors(req, badRequest("Already verified"));

      const otp = generateOtp(6);
      const ts = nowMs();
      await env.OTP_KV.put(`otp:${user.email}`, JSON.stringify({ otp, user_id: user.id, created_at: ts }), { expirationTtl: OTP_TTL_SECONDS });
      await _send_otp_email(env, user.email, otp);
      return withCors(req, json({ ok: true }));
    }

    if (url.pathname === "/api/auth/verify-otp" && req.method === "POST") {
      const body = await readJson<{ email: string; otp: string }>(req);
      if (!body) return withCors(req, badRequest("Invalid JSON"));

      const email = String(body.email || "").trim().toLowerCase();
      const otp = String(body.otp || "").trim();
      if (!email || !otp) return withCors(req, badRequest("Missing fields"));

      const stored = await env.OTP_KV.get(`otp:${email}`);
      if (!stored) return withCors(req, badRequest("OTP expired"));

      let parsed: any;
      try {
        parsed = JSON.parse(stored);
      } catch {
        return withCors(req, badRequest("OTP invalid"));
      }

      if (String(parsed.otp) !== otp) return withCors(req, badRequest("OTP invalid"));

      const userId = String(parsed.user_id || "");
      if (!userId) return withCors(req, badRequest("OTP invalid"));

      await env.DB.prepare("UPDATE users SET is_otp_verified = 1, updated_at = ? WHERE id = ?")
        .bind(nowMs(), userId)
        .run();

      // Create session
      const token = randomId("sess");
      await env.SESSION_KV.put(`sess:${token}`, userId, { expirationTtl: SESSION_TTL_SECONDS });

      const headers = new Headers();
      headers.append(
        "set-cookie",
        setCookie(sessionCookieName(env), token, { maxAgeSeconds: SESSION_TTL_SECONDS, httpOnly: true, sameSite: "Lax", secure: true }),
      );

      return withCors(req, json({ ok: true }, { headers }));
    }

    if (url.pathname === "/api/auth/login" && req.method === "POST") {
      const body = await readJson<{ email_or_phone: string; password: string }>(req);
      if (!body) return withCors(req, badRequest("Invalid JSON"));

      const ident = String(body.email_or_phone || "").trim().toLowerCase();
      const password = String(body.password || "");
      if (!ident || !password) return withCors(req, badRequest("Missing fields"));

      const row = await env.DB.prepare(
        "SELECT id, password_hash, is_otp_verified FROM users WHERE email = ? OR phone = ?",
      )
        .bind(ident, ident)
        .first<{ id: string; password_hash: string; is_otp_verified: number }>();

      if (!row) return withCors(req, unauthorized("Invalid credentials"));
      if (!row.is_otp_verified) return withCors(req, unauthorized("Verify OTP first"));

      const ok = await verifyPassword(password, row.password_hash, secret(env));
      if (!ok) return withCors(req, unauthorized("Invalid credentials"));

      const token = randomId("sess");
      await env.SESSION_KV.put(`sess:${token}`, row.id, { expirationTtl: SESSION_TTL_SECONDS });

      const headers = new Headers();
      headers.append(
        "set-cookie",
        setCookie(sessionCookieName(env), token, { maxAgeSeconds: SESSION_TTL_SECONDS, httpOnly: true, sameSite: "Lax", secure: true }),
      );

      return withCors(req, json({ ok: true }, { headers }));
    }

    if (url.pathname === "/api/auth/logout" && req.method === "POST") {
      const cookies = parseCookies(req.headers.get("cookie"));
      const token = cookies[sessionCookieName(env)];
      if (token) await env.SESSION_KV.delete(`sess:${token}`);

      const headers = new Headers();
      headers.append(
        "set-cookie",
        setCookie(sessionCookieName(env), "", { maxAgeSeconds: 0, httpOnly: true, sameSite: "Lax", secure: true }),
      );
      return withCors(req, json({ ok: true }, { headers }));
    }

    // --- MESSAGING ---
    if (url.pathname === "/api/messages/threads" && req.method === "GET") {
      const user = await getUserFromSession(req, env);
      if (!user) return withCors(req, unauthorized());

      const rows = await env.DB.prepare(
        `SELECT c.id as id, c.updated_at as updated_at
         FROM conversations c
         JOIN conversation_participants p ON p.conversation_id = c.id
         WHERE p.user_id = ?
         ORDER BY c.updated_at DESC`,
      )
        .bind(user.id)
        .all<{ id: string; updated_at: number }>();

      return withCors(req, json({ threads: rows.results }));
    }

    const convoMatch = url.pathname.match(/^\/api\/messages\/([A-Za-z0-9_\-]+)$/);
    if (convoMatch && req.method === "GET") {
      const user = await getUserFromSession(req, env);
      if (!user) return withCors(req, unauthorized());
      const convoId = convoMatch[1];

      const membership = await env.DB.prepare(
        "SELECT 1 as ok FROM conversation_participants WHERE conversation_id = ? AND user_id = ?",
      )
        .bind(convoId, user.id)
        .first<{ ok: number }>();

      if (!membership) return withCors(req, unauthorized());

      const msgs = await env.DB.prepare(
        "SELECT id, sender_id, text, created_at FROM messages WHERE conversation_id = ? ORDER BY created_at ASC LIMIT 200",
      )
        .bind(convoId)
        .all<{ id: string; sender_id: string; text: string; created_at: number }>();

      return withCors(req, json({ conversation_id: convoId, messages: msgs.results }));
    }

    const sendMatch = url.pathname.match(/^\/api\/messages\/([A-Za-z0-9_\-]+)\/send$/);
    if (sendMatch && req.method === "POST") {
      const user = await getUserFromSession(req, env);
      if (!user) return withCors(req, unauthorized());
      const convoId = sendMatch[1];

      const membership = await env.DB.prepare(
        "SELECT 1 as ok FROM conversation_participants WHERE conversation_id = ? AND user_id = ?",
      )
        .bind(convoId, user.id)
        .first<{ ok: number }>();

      if (!membership) return withCors(req, unauthorized());

      const body = await readJson<{ text: string }>(req);
      if (!body) return withCors(req, badRequest("Invalid JSON"));
      const text = String(body.text || "").trim();
      if (!text) return withCors(req, badRequest("Empty message"));

      const msgId = randomId("msg");
      const ts = nowMs();
      await env.DB.prepare(
        "INSERT INTO messages (id, conversation_id, sender_id, text, created_at) VALUES (?, ?, ?, ?, ?)",
      )
        .bind(msgId, convoId, user.id, text, ts)
        .run();

      await env.DB.prepare("UPDATE conversations SET updated_at = ? WHERE id = ?").bind(ts, convoId).run();

      // TODO: Add email notifications if needed

      return withCors(req, json({ ok: true, message: { id: msgId, sender_id: user.id, text, created_at: ts } }));
    }

    if (url.pathname === "/api/messages/start" && req.method === "POST") {
      const user = await getUserFromSession(req, env);
      if (!user) return withCors(req, unauthorized());

      const body = await readJson<{ other_user_id: string }>(req);
      if (!body) return withCors(req, badRequest("Invalid JSON"));
      const otherId = String(body.other_user_id || "").trim();
      if (!otherId) return withCors(req, badRequest("Missing other_user_id"));

      const other = await env.DB.prepare("SELECT id FROM users WHERE id = ?").bind(otherId).first<{ id: string }>();
      if (!other) return withCors(req, badRequest("User not found"));

      // Try to find existing 1:1 conversation
      const existing = await env.DB.prepare(
        `SELECT c.id as id
         FROM conversations c
         JOIN conversation_participants p1 ON p1.conversation_id = c.id AND p1.user_id = ?
         JOIN conversation_participants p2 ON p2.conversation_id = c.id AND p2.user_id = ?
         WHERE (SELECT COUNT(*) FROM conversation_participants px WHERE px.conversation_id = c.id) = 2
         LIMIT 1`,
      )
        .bind(user.id, otherId)
        .first<{ id: string }>();

      if (existing?.id) return withCors(req, json({ conversation_id: existing.id }));

      const convoId = randomId("convo");
      const ts = nowMs();
      await env.DB.prepare("INSERT INTO conversations (id, created_at, updated_at) VALUES (?, ?, ?)").bind(convoId, ts, ts).run();
      await env.DB.prepare("INSERT INTO conversation_participants (conversation_id, user_id) VALUES (?, ?)").bind(convoId, user.id).run();
      await env.DB.prepare("INSERT INTO conversation_participants (conversation_id, user_id) VALUES (?, ?)").bind(convoId, otherId).run();

      return withCors(req, json({ conversation_id: convoId }));
    }

    return withCors(req, notFound());
  },
};
