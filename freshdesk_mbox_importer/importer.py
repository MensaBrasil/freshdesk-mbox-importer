"""Freshdesk MBOX Importer"""

import time
import mailbox
import re
from collections.abc import Iterable
from email.utils import parseaddr, parsedate_to_datetime
from email.header import decode_header

import httpx
from pydantic import BaseModel, Field

from .settings import ImporterSettings

settings = ImporterSettings()
_SPAM_ADDR = re.compile(r"(mailer-daemon@|postmaster@|no[-_]reply@)", re.I)
_SKIP_LABELS = {"spam", "trash"}


class TicketPayload(BaseModel):
    """Model for Freshdesk ticket creation."""
    email: str
    subject: str
    description: str
    status: int = 5
    priority: int = 1
    custom_fields: dict = Field(default_factory=dict)


def _decode(text: str) -> str:
    """Decode RFC2047 encoded header text."""
    parts = decode_header(text or "")
    return "".join(
        b.decode(enc or "utf-8", errors="replace") if isinstance(b, bytes) else b
        for b, enc in parts
    )


def _is_spam(headers: dict) -> bool:
    """Return True if the message is spam or trash."""
    labels = {lbl.strip().lower() for lbl in headers.get("X-Gmail-Labels", "").split(",")}
    if labels & _SKIP_LABELS:
        return True
    if headers.get("Precedence", "").lower() in {"bulk", "junk", "list"}:
        return True
    if headers.get("Auto-Submitted", "").lower() not in {"", "no"}:
        return True
    if "all" in headers.get("X-Auto-Response-Suppress", "").lower():
        return True
    sender = parseaddr(headers.get("From", ""))[1]
    return bool(_SPAM_ADDR.search(sender))


def iter_messages(path: str) -> Iterable[tuple[dict, str]]:
    """Yield header/body pairs from an mbox file."""
    for msg in mailbox.mbox(path):
        hdrs = dict(msg.items())
        payload = msg.get_payload(decode=True)
        body = payload.decode(errors="replace") if isinstance(payload, bytes) else str(payload)
        yield hdrs, body


def ensure_custom_field() -> None:
    url = f"https://{settings.fd_domain}.freshdesk.com/api/v2/ticket_fields"
    resp = httpx.get(url, auth=(settings.fd_key, "X"))
    resp.raise_for_status()
    names = {f["name"] for f in resp.json()}
    if settings.original_date_field not in names:
        raise RuntimeError(
            f"Custom field {settings.original_date_field!r} not found. "
            "Please create it under Admin → Workflows → Ticket Fields, as `original_date`. Freshdesk adds  `cf` prefix to the field name."
        )


def build_ticket(headers: dict, body: str) -> TicketPayload:
    """Build a TicketPayload from email headers and body."""
    sent_at = parsedate_to_datetime(headers.get("Date", ""))  
    return TicketPayload(
        email=parseaddr(headers.get("From", ""))[1] or "unknown@example.com",
        subject=_decode(headers.get("Subject", "")) or "(no subject)",
        description=body,
        custom_fields={settings.original_date_field: sent_at.date().isoformat()},
    )


def push(ticket: TicketPayload) -> None:
    """Send a ticket to Freshdesk via the API."""
    url = f"https://{settings.fd_domain}.freshdesk.com/api/v2/tickets"
    resp = httpx.post(url, auth=(settings.fd_key, "X"), json=ticket.model_dump())
    print(f"Response: {resp.status_code} {resp.reason_phrase} {resp.text}")
    print(f"Ticket created: {ticket.subject} ({ticket.email})")
    time.sleep(settings.rate_delay)


def sync() -> None:
    """Read the mbox and push each non-spam message as a ticket."""
    ensure_custom_field()
    print(f"Reading mbox file: {settings.mbox_path}")
    for headers, body in iter_messages(settings.mbox_path):
        if _is_spam(headers):
            continue
        push(build_ticket(headers, body))


if __name__ == "__main__":
    sync()
