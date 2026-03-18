from __future__ import annotations

from app.core.config import get_settings
from starlette.concurrency import run_in_threadpool
import httpx

settings = get_settings()


def _normalize_whatsapp_to(phone: str | None) -> str | None:
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


def _twilio_ready() -> bool:
    return bool(settings.twilio_account_sid and settings.twilio_auth_token and settings.twilio_whatsapp_from)


def _wa_web_ready() -> bool:
    return bool(settings.wa_web_service_url and settings.wa_web_service_auth_token)


def _send_whatsapp_sync(to_phone: str | None, body: str) -> str | None:
    if not _twilio_ready():
        return "Twilio WhatsApp not configured"

    to_e164 = _normalize_whatsapp_to(to_phone)
    if not to_e164:
        return "Invalid phone"

    from twilio.rest import Client

    try:
        client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
        client.messages.create(
            from_=str(settings.twilio_whatsapp_from).strip(),
            body=body,
            to=f"whatsapp:{to_e164}",
        )
    except Exception as exc:
        return str(exc)

    return None


async def send_whatsapp(to_phone: str | None, body: str) -> str | None:
    provider = str(getattr(settings, "whatsapp_provider", "twilio") or "twilio").strip().lower()

    if provider == "wa_web":
        if not _wa_web_ready():
            return "WhatsApp web service not configured"

        to_e164 = _normalize_whatsapp_to(to_phone)
        if not to_e164:
            return "Invalid phone"

        def _call_wa_web() -> str | None:
            url = str(settings.wa_web_service_url).rstrip("/") + "/send"
            headers = {
                "Authorization": f"Bearer {str(settings.wa_web_service_auth_token).strip()}",
                "ngrok-skip-browser-warning": "true",
            }
            payload = {"to": to_e164, "body": body}
            with httpx.Client(timeout=15.0) as client:
                resp = client.post(url, json=payload, headers=headers)
            if resp.status_code >= 200 and resp.status_code < 300:
                data = resp.json() if resp.content else {}
                if data.get("ok") is True:
                    return None
                return str(data.get("error") or "unknown_error")
            try:
                data = resp.json()
                return str(data.get("error") or resp.text or f"HTTP {resp.status_code}")
            except Exception:
                return resp.text or f"HTTP {resp.status_code}"

        return await run_in_threadpool(_call_wa_web)

    return await run_in_threadpool(_send_whatsapp_sync, to_phone, body)
