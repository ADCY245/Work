from __future__ import annotations

import base64
import smtplib
from email.message import EmailMessage
from typing import Iterable

import resend

from app.core.config import get_settings

settings = get_settings()


def _send_with_resend(
    subject: str,
    body: str,
    to_emails: Iterable[str],
    attachments: list[tuple[str, bytes, str]] | None = None,
) -> None:
    if not settings.resend_api_key:
        raise RuntimeError("Resend API key is not configured")

    resend.api_key = settings.resend_api_key

    payload: dict[str, object] = {
        "from": settings.notifications_from_email,
        "to": list(to_emails),
        "subject": subject,
        "text": body,
    }

    if attachments:
        payload["attachments"] = [
            {
                "filename": filename,
                "content": base64.b64encode(data).decode("utf-8"),
            }
            for filename, data, _ in attachments
        ]

    resend.Emails.send(payload)


def _send_with_smtp(
    subject: str,
    body: str,
    to_emails: Iterable[str],
    attachments: list[tuple[str, bytes, str]] | None = None,
) -> None:
    if not settings.smtp_host or not settings.smtp_port:
        raise RuntimeError("SMTP is not configured. Set SMTP_HOST and SMTP_PORT.")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.notifications_from_email
    msg["To"] = ", ".join(to_emails)
    msg.set_content(body)

    if attachments:
        for filename, data, content_type in attachments:
            maintype, subtype = (content_type or "application/octet-stream").split("/", 1)
            msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)

    smtp_kwargs = {
        "host": settings.smtp_host,
        "port": settings.smtp_port,
    }

    if settings.smtp_use_tls and settings.smtp_port == 465:
        smtp_client = smtplib.SMTP_SSL(**smtp_kwargs)
    else:
        smtp_client = smtplib.SMTP(**smtp_kwargs)

    with smtp_client as server:
        if settings.smtp_use_tls and settings.smtp_port != 465:
            server.starttls()
        if settings.smtp_username and settings.smtp_password:
            server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(msg)


def send_email(
    subject: str,
    body: str,
    to_emails: Iterable[str],
    attachments: list[tuple[str, bytes, str]] | None = None,
) -> None:
    last_error: Exception | None = None

    if settings.resend_api_key:
        try:
            _send_with_resend(subject, body, to_emails, attachments)
            return
        except Exception as exc:  # pragma: no cover - want visibility in UI
            last_error = exc

    try:
        _send_with_smtp(subject, body, to_emails, attachments)
        return
    except Exception as exc:  # pragma: no cover - want visibility in UI
        last_error = exc

    if last_error:
        raise last_error

