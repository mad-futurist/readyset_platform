from ssl import SSLContext
from unittest.mock import patch

from app.config import Settings
from app.email import CaptureEmailSender, SmtpEmailSender, create_email_sender


def test_capture_sender_keeps_message_in_memory() -> None:
    sender = create_email_sender(Settings(environment="test", email_backend="capture"))
    assert isinstance(sender, CaptureEmailSender)
    sender.send("person@example.com", "Subject", "Body")
    assert sender.outbox[0].recipient == "person@example.com"
    assert sender.outbox[0].body == "Body"


def test_smtp_sender_uses_starttls_authentication_and_configured_sender() -> None:
    settings = Settings(
        environment="test",
        email_backend="smtp",
        email_from="ReadySet <no-reply@example.com>",
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_username="mailer",
        smtp_password="mail-secret",
        smtp_starttls=True,
    )
    sender = SmtpEmailSender(settings)
    with patch("app.email.smtplib.SMTP") as smtp:
        connection = smtp.return_value.__enter__.return_value
        sender.send("person@example.com", "Verify", "Follow the verification link")

    smtp.assert_called_once_with("smtp.example.com", 587, timeout=10)
    connection.starttls.assert_called_once()
    assert isinstance(connection.starttls.call_args.kwargs["context"], SSLContext)
    connection.login.assert_called_once_with("mailer", "mail-secret")
    message = connection.send_message.call_args.args[0]
    assert message["From"] == "ReadySet <no-reply@example.com>"
    assert message["To"] == "person@example.com"
    assert message["Subject"] == "Verify"
