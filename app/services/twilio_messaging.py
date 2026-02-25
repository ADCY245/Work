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


def _twilio_ready() -> bool:
    return bool(settings.twilio_account_sid and settings.twilio_auth_token)


async def _send_twilio_message(*, to: str, from_: str, body: str) -> str | None:
    if not _twilio_ready():
        return "Twilio not configured"
    if not to or not from_:
        return "Missing to/from"

    url = f"https://api.twilio.com/2010-04-01/Accounts/{settings.twilio_account_sid}/Messages.json"
    data: dict[str, Any] = {"To": to, "From": from_, "Body": body}

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            res = await client.post(
                url,
                data=data,
                auth=(settings.twilio_account_sid, settings.twilio_auth_token),
                headers={"Accept": "application/json"},
            )
        except Exception as exc:
            return str(exc)

    if res.status_code >= 400:
        try:
            payload = res.json()
            msg = payload.get("message") or payload.get("error_message")
            if msg:
                return str(msg)
        except Exception:
            pass
        return f"Twilio error ({res.status_code})"

    return None


async def send_sms(to_phone: str | None, body: str) -> str | None:
    to_e164 = _normalize_to_e164(to_phone)
    if not to_e164:
        return "Invalid phone"
    from_ = str(settings.twilio_sms_from or "").strip()
    if not from_:
        return "TWILIO_SMS_FROM not configured"
    return await _send_twilio_message(to=to_e164, from_=from_, body=body)


async def send_whatsapp(to_phone: str | None, body: str) -> str | None:
    to_e164 = _normalize_to_e164(to_phone)
    if not to_e164:
        return "Invalid phone"
    from_ = str(settings.twilio_whatsapp_from or "").strip()
    if not from_:
        return "TWILIO_WHATSAPP_FROM not configured"

    to = to_e164
    if not to.startswith("whatsapp:"):
        to = "whatsapp:" + to
    if not from_.startswith("whatsapp:"):
        from_ = "whatsapp:" + from_

    return await _send_twilio_message(to=to, from_=from_, body=body)
