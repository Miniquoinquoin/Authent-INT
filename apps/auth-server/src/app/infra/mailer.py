"""SMTP, in a thread. Two HTML mails, one Jinja file each in `templates/`.
Never swallows a send failure (§8)."""

import asyncio
import logging
import re
import smtplib
from email.message import EmailMessage
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from app.config import settings

log = logging.getLogger(__name__)

# autoescape: `prenom` and `to` are user data. StrictUndefined: a typo'd
# variable in a template fails the send loudly instead of mailing a blank.
_env = Environment(
    loader=FileSystemLoader(Path(__file__).with_name("templates")),
    autoescape=True,
    undefined=StrictUndefined,
)


def _render(template: str, **vars) -> tuple[str, str]:
    """(subject, html). The subject is the template's <title>, so one file
    holds the whole mail and a browser tab previews the subject too."""
    # The logo is served by the frontend, so the same PUBLIC_BASE_URL rule as
    # the links (P§2) — no attachment, no second copy of the asset.
    html = _env.get_template(template).render(base_url=settings().public_base_url, **vars)
    subject = re.search(r"<title>(.*?)</title>", html, re.S).group(1).strip()
    return subject, html


def _send(message: EmailMessage) -> None:
    cfg = settings()
    with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=10) as smtp:
        smtp.send_message(message)


async def _deliver(to: str, kind: str, template: str, **vars) -> None:
    subject, html = _render(template, **vars)
    message = EmailMessage()
    message["From"] = settings().mail_from
    message["To"] = to
    message["Subject"] = subject
    message.set_content(html, subtype="html")
    # stdlib smtplib is blocking; a thread keeps it off the event loop, exactly
    # like Argon2. No aiosmtplib dependency for two mails (P§10).
    await asyncio.to_thread(_send, message)
    # The address is not logged: it is a directory attribute of an identified
    # person, and §5's rule about the numéro fiscal is the same rule.
    log.info(kind, extra={"event": {"event_type": kind, "outcome": "success"}})


async def send_activation(to: str, prenom: str, token: str) -> None:
    """The activation link, built from PUBLIC_BASE_URL and never a literal (P§2)."""
    link = f"{settings().public_base_url}/activer?token={token}"
    await _deliver(
        to,
        "activation.sent",
        "activation.html",
        prenom=prenom,
        link=link,
        ttl_min=settings().activation_ttl_s // 60,
    )


async def send_otp(to: str, code: str) -> None:
    await _deliver(
        to,
        "otp.sent",
        "otp.html",
        email=to,
        code=code,
        ttl_min=settings().otp_ttl_s // 60,
    )


if __name__ == "__main__":
    # Preview + self-check:  python -m app.infra.mailer otp > /tmp/otp.html
    import sys

    samples = {
        "otp": dict(email="jean.dupont@example.org", code="482391", ttl_min=10),
        "activation": dict(prenom="Jean", link="http://localhost:5173/activer?token=abc-123", ttl_min=30),
    }
    which = sys.argv[1] if len(sys.argv) > 1 else "otp"
    subject, html = _render(f"{which}.html", **samples[which])
    assert subject.startswith(("Votre code", "Activation")), subject
    assert "482391" in html or "abc-123" in html
    print(html)
