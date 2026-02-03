from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Iterable

from app.core.config import get_settings

settings = get_settings()


def send_email(
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

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
        if settings.smtp_use_tls:
            server.starttls()
        if settings.smtp_username and settings.smtp_password:
            server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(msg)
