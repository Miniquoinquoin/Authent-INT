import logging
from typing import Protocol

log = logging.getLogger(__name__)

# Defines an abstraction for the mailer so that it can be easily switched from console log to SMTP
class Mailer(Protocol):
    async def send(self, to: str, subject: str, body: str) -> None: ...

class ConsoleMailer:
    async def send(self, to: str, subject: str, body: str):
        log.warning("mail to=%s subject=%r\n%s", to, subject, body)  # dev: the link shows in `make logs`

def get_mailer() -> Mailer:
    """FastAPI dependency: SmtpMailer replaces ConsoleMailer here once the client picks a relay (ADR §18 q.6)."""

    return ConsoleMailer()
