"""Freshdesk MBOX Importer"""

import time
import mailbox
import sys

from email.utils import parsedate_to_datetime

import httpx
from pydantic import BaseModel, Field

from .settings import ImporterSettings

settings = ImporterSettings()


class TicketPayload(BaseModel):
    """Data model for Freshdesk ticket creation."""
    requester: dict
    subject: str
    description: str
    status: int = 5
    priority: int = 1
    custom_fields: dict = Field(default_factory=dict)


def iter_messages(path: str) -> Iterable[tuple[dict, str]]:
    """Yield (headers, body) tuples from the mbox file."""
    for msg in mailbox.mbox(path):
        hdrs = dict(msg.items())
        payload = msg.get_payload(decode=True)
        if isinstance(payload, bytes):
            body = payload.decode(errors="replace")
        else:
            body = str(payload)
        yield hdrs, body


def build_ticket(headers: dict, body: str) -> TicketPayload:
    """Construct a TicketPayload from email headers and body."""
    return TicketPayload(
        requester={"email": headers.get("From", "unknown@example.com")},
        subject=headers.get("Subject", "(no subject)"),
        description=body,
    )


def push(ticket: TicketPayload) -> None:
    """Send the ticket to Freshdesk via API."""
    url = f"https://{settings.fd_domain}.freshdesk.com/api/v2/tickets"
    auth = (settings.fd_key, "X")
    resp = httpx.post(url, auth=auth, json=ticket.model_dump())
    print(f"Response: {resp.status_code} {resp.reason_phrase} {resp.text}")
    print(f"Ticket created: {ticket.subject} ({ticket.requester['email']})")
    time.sleep(settings.rate_delay)


def sync() -> None:
    """Main function to read mbox and push tickets to Freshdesk."""
    print(f"Reading mbox file: {settings.mbox_path}")
    for headers, body in iter_messages(settings.mbox_path):
        push(build_ticket(headers, body))


