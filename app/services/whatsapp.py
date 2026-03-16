from __future__ import annotations

from app.core.config import get_settings

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


def send_whatsapp(to_phone: str | None, body: str) -> str | None:
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
