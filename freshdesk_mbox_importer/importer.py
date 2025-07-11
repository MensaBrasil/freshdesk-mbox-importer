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


class TicketPayload(BaseModel):
    email: str
    subject: str
    description: str
    status: int = 5
    priority: int = 1
    custom_fields: dict = Field(default_factory=dict)


_spam_addr = re.compile(r"(mailer-daemon@|postmaster@|no[-_]reply@)", re.I)


def _decode(text: str) -> str:
    parts = decode_header(text)
    return "".join(
        (b.decode(enc or "utf-8", errors="replace") if isinstance(b, bytes) else b)
        for b, enc in parts
    )


def _is_spam(h: dict) -> bool:
    """Determine if the message is likely spam based on headers."""
    if h.get("Precedence", "").lower() in {"bulk", "junk", "list"}:
        return True
    if h.get("Auto-Submitted", "").lower() not in {"", "no"}:
        return True
    if "all" in h.get("X-Auto-Response-Suppress", "").lower():
        return True
    sender = parseaddr(h.get("From", ""))[1]
    return bool(_spam_addr.search(sender))


def iter_messages(path: str) -> Iterable[tuple[dict, str]]:
    for msg in mailbox.mbox(path):
        hdrs = dict(msg.items())
        payload = msg.get_payload(decode=True)
        body = payload.decode(errors="replace") if isinstance(payload, bytes) else str(payload)
        yield hdrs, body


def build_ticket(headers: dict, body: str) -> TicketPayload:
    sent_at = parsedate_to_datetime(headers.get("Date", ""))  # may raise if blank
    return TicketPayload(
        email=parseaddr(headers.get("From", ""))[1] or "unknown@example.com",
        subject=_decode(headers.get("Subject", "")) or "(no subject)",
        description=body,
        custom_fields={settings.original_date_field: sent_at.date().isoformat()},
    )


def push(ticket: TicketPayload) -> None:
    url = f"https://{settings.fd_domain}.freshdesk.com/api/v2/tickets"
    resp = httpx.post(url, auth=(settings.fd_key, "X"), json=ticket.model_dump())
    print(f"Response: {resp.status_code} {resp.reason_phrase} {resp.text}")
    print(f"Ticket created: {ticket.subject} ({ticket.email})")
    time.sleep(settings.rate_delay)


def sync() -> None:
    print(f"Reading mbox file: {settings.mbox_path}")
    for headers, body in iter_messages(settings.mbox_path):
        if _is_spam(headers):
            continue
        push(build_ticket(headers, body))


if __name__ == "__main__":
    sync()
