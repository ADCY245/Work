from __future__ import annotations

from typing import Any

import httpx

from app.core.config import get_settings

settings = get_settings()


def _normalize_to_e164(phone: str | None) -> str | None:
    raw = str(phone or "").strip()
    if not raw:
        return None

    digits = "".join(ch for ch in raw if ch.isdigit())
    if raw.startswith("+"):
        if not digits:
            return None
        return "+" + digits

    if len(digits) == 10:
        return "+91" + digits
    if len(digits) >= 11 and digits.startswith("91"):
        return "+" + digits
    return None


def _meta_ready() -> bool:
    return bool(settings.meta_whatsapp_token and settings.meta_whatsapp_phone_number_id)


async def send_whatsapp(to_phone: str | None, body: str) -> str | None:
    if not _meta_ready():
        return "Meta WhatsApp not configured"

    to_e164 = _normalize_to_e164(to_phone)
    if not to_e164:
        return "Invalid phone"

    version = str(settings.meta_whatsapp_api_version or "v19.0").strip() or "v19.0"
    url = f"https://graph.facebook.com/{version}/{settings.meta_whatsapp_phone_number_id}/messages"

    payload: dict[str, Any] = {
        "messaging_product": "whatsapp",
        "to": to_e164,
        "type": "text",
        "text": {"body": body},
    }

    headers = {
        "Authorization": f"Bearer {settings.meta_whatsapp_token}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            res = await client.post(url, json=payload, headers=headers)
        except Exception as exc:
            return str(exc)

    if res.status_code >= 400:
        try:
            data = res.json()
            err = (data or {}).get("error") or {}
            msg = err.get("message")
            if msg:
                return str(msg)
        except Exception:
            pass
        return f"Meta WhatsApp error ({res.status_code})"

    return None
