import { normalizeToE164 } from "./utils";
import type { Env } from "./types";

export async function sendWhatsApp(env: Env, toPhone: string | null | undefined, body: string): Promise<string | null> {
  const token = (env.META_WHATSAPP_TOKEN || "").trim();
  const phoneNumberId = (env.META_WHATSAPP_PHONE_NUMBER_ID || "").trim();
  if (!token || !phoneNumberId) return "Meta WhatsApp not configured";

  const to = normalizeToE164(toPhone);
  if (!to) return "Invalid phone";

  const version = (env.META_WHATSAPP_API_VERSION || "v19.0").trim() || "v19.0";
  const url = `https://graph.facebook.com/${version}/${phoneNumberId}/messages`;

  const res = await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      messaging_product: "whatsapp",
      to,
      type: "text",
      text: { body },
    }),
  });

  if (res.status >= 400) {
    try {
      const data: any = await res.json();
      const msg = data?.error?.message;
      if (msg) return String(msg);
    } catch {
      // ignore
    }
    return `Meta WhatsApp error (${res.status})`;
  }

  return null;
}
