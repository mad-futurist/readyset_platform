import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Protocol

from fastapi import Request

from app.config import EmailBackend, Settings


@dataclass(frozen=True)
class CapturedEmail:
    recipient: str
    subject: str
    body: str


class EmailSender(Protocol):
    def send(self, recipient: str, subject: str, body: str) -> None: ...


class CaptureEmailSender:
    """Deterministic development/test delivery; tokens never reach logs."""

    def __init__(self) -> None:
        self.outbox: list[CapturedEmail] = []

    def send(self, recipient: str, subject: str, body: str) -> None:
        self.outbox.append(CapturedEmail(recipient=recipient, subject=subject, body=body))


class SmtpEmailSender:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def send(self, recipient: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = self.settings.email_from
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(body)
        if not self.settings.smtp_host:
            raise RuntimeError("SMTP is not configured")
        with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=10) as smtp:
            if self.settings.smtp_starttls:
                smtp.starttls(context=ssl.create_default_context())
            if self.settings.smtp_username and self.settings.smtp_password:
                smtp.login(self.settings.smtp_username, self.settings.smtp_password)
            smtp.send_message(message)


def create_email_sender(settings: Settings) -> EmailSender:
    if settings.email_backend == EmailBackend.SMTP:
        return SmtpEmailSender(settings)
    return CaptureEmailSender()


def get_email_sender(request: Request) -> EmailSender:
    return request.app.state.email_sender  # type: ignore[no-any-return]
