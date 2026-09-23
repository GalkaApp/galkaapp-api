import asyncio
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from app.config import Settings


@dataclass
class Email:
    to: str
    subject: str
    text: str
    html: str


class Mailer:
    """Interface: SMTP in production, an in-memory outbox in tests."""

    async def send(self, email: Email) -> None:
        raise NotImplementedError


class SmtpMailer(Mailer):
    """Blocking smtplib run in a thread; STARTTLS on 587, implicit TLS on 465."""

    def __init__(self, host: str, port: int, username: str, password: str, sender: str, sender_name: str):
        self.host, self.port = host, port
        self.username, self.password = username, password
        self.sender, self.sender_name = sender or username, sender_name

    @classmethod
    def from_settings(cls, settings: Settings) -> "SmtpMailer | None":
        if not settings.smtp_host:
            return None
        return cls(settings.smtp_host, settings.smtp_port, settings.smtp_username,
                   settings.smtp_password, settings.smtp_from, settings.smtp_from_name)

    def _message(self, email: Email) -> EmailMessage:
        message = EmailMessage()
        message["From"] = formataddr((self.sender_name, self.sender))
        message["To"] = email.to
        message["Subject"] = email.subject
        message["Message-ID"] = make_msgid(domain=self.sender.rpartition("@")[2] or None)
        message.set_content(email.text)
        message.add_alternative(email.html, subtype="html")
        return message

    def _send_blocking(self, message: EmailMessage) -> None:
        context = ssl.create_default_context()
        if self.port == 465:
            client = smtplib.SMTP_SSL(self.host, self.port, timeout=30, context=context)
        else:
            client = smtplib.SMTP(self.host, self.port, timeout=30)
        with client:
            if self.port != 465:
                client.starttls(context=context)
            if self.username:
                client.login(self.username, self.password)
            client.send_message(message)

    async def send(self, email: Email) -> None:
        await asyncio.to_thread(self._send_blocking, self._message(email))


class InMemoryMailer(Mailer):
    def __init__(self):
        self.outbox: list[Email] = []

    async def send(self, email: Email) -> None:
        self.outbox.append(email)
