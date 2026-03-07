import type { Env } from "./types";

export async function send_email(env: Env, to: string, subject: string, body: string): Promise<string | null> {
  const key = env.RESEND_API_KEY;
  if (!key) return "Resend API key not configured";

  const res = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${key}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      from: "PhysiHome <noreply@yourdomain.com>",
      to,
      subject,
      html: body,
    }),
  });

  if (res.status >= 400) {
    try {
      const data = await res.json();
      return data?.message || `Email error (${res.status})`;
    } catch {
      return `Email error (${res.status})`;
    }
  }

  return null;
}
