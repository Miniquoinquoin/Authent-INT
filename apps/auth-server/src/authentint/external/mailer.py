import logging
from typing import Protocol

log = logging.getLogger(__name__)

# Defines an abstraction for the mailer so that it can be easily switched from console log to SMTP
class Mailer(Protocol):
    async def send(self, to: str, subject: str, body: str) -> None: ...

class ConsoleMailer:
    async def send(self, to: str, subject: str, body: str):
        log.info("mail", extra={"to": to, "subject": subject, "body": body})
