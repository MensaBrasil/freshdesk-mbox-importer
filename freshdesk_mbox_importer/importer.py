"""Freshdesk MBOX Importer with SQLite resume, purge prompt and progress bar"""

import time
import mailbox
import re
import html
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from email.utils import parseaddr, parsedate_to_datetime
from email.header import decode_header
import signal
import sys

import httpx
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type
from pydantic import BaseModel, Field

from .settings import ImporterSettings

try:
    from tqdm.auto import tqdm
except ModuleNotFoundError:
    tqdm = None  # type: ignore

settings = ImporterSettings()
_DB_PATH = Path(".fd_progress.db")
_SPAM_ADDR = re.compile(r"(mailer-daemon@|postmaster@|no[-_]reply@)", re.I)
_SKIP_LABELS = {"spam", "trash"}
_HTML_RE = re.compile(r"<[a-z][\s\S]*>", re.I | re.M)


class TicketPayload(BaseModel):
    """Payload sent to Freshdesk."""
    email: str | None = None
    name: str | None = None
    subject: str
    description: str
    status: int = 5
    priority: int = 1
    tags: list[str] = Field(default_factory=list)
    group_id: int | None = None
    custom_fields: dict = Field(default_factory=dict)


def _decode(text: str) -> str:
    """Decode RFC-2047 header text."""
    parts = decode_header(text or "")
    return "".join(
        b.decode(enc or "utf-8", errors="replace") if isinstance(b, bytes) else b
        for b, enc in parts
    )


def _is_spam(headers: dict) -> bool:
    """Return True if the message should be skipped."""
    labels = {l.strip().lower() for l in headers.get("X-Gmail-Labels", "").split(",")}
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
    """Yield headers and body for each non-empty message."""
    for msg in mailbox.mbox(path):
        hdrs = dict(msg.items())
        payload = msg.get_payload(decode=True)
        body = payload.decode(errors="replace") if isinstance(payload, bytes) else str(payload or "")
        if not body.strip():
            continue
        yield hdrs, body


def ensure_custom_field() -> None:
    """Abort if the required custom date field is absent."""
    url = f"https://{settings.fd_domain}.freshdesk.com/api/v2/ticket_fields"
    resp = httpx.get(url, auth=(settings.fd_key, "X"))
    resp.raise_for_status()
    names = {f["name"] for f in resp.json()}
    if settings.original_date_field not in names:
        raise RuntimeError(f"Create a Date field named {settings.original_date_field!r} in Freshdesk")


def ensure_import_group() -> int:
    """Return the ID of the import group, prompting if missing."""
    url = f"https://{settings.fd_domain}.freshdesk.com/api/v2/groups"
    resp = httpx.get(url, auth=(settings.fd_key, "X"))
    resp.raise_for_status()
    for g in resp.json():
        if g.get("name") == settings.import_group_name:
            return g["id"]
    input(f"Group '{settings.import_group_name}' not found. Create it in Admin → Groups then press Enter to continue…")
    resp = httpx.get(url, auth=(settings.fd_key, "X"))
    resp.raise_for_status()
    for g in resp.json():
        if g.get("name") == settings.import_group_name:
            return g["id"]
    raise RuntimeError(f"Group '{settings.import_group_name}' is missing")


def _html_block(headers: dict, body: str) -> str:
    """Return an HTML fragment for one e-mail."""
    ts = parsedate_to_datetime(headers.get("Date", "")).isoformat(" ", "seconds")
    sender = _decode(headers.get("From", "")).strip()
    head = f"<strong>{html.escape(ts)}"
    if sender:
        head += f" {html.escape(sender)}"
    head += "</strong>"
    if _HTML_RE.search(body):
        return f"<p>{head}</p>{body}"
    body_html = html.escape(body).replace("\n", "<br>")
    return f"<p>{head}<br>{body_html}</p>"


def build_thread_ticket(messages: list[tuple[dict, str]], group_id: int) -> TicketPayload:
    """Return one ticket covering a Gmail thread."""
    messages.sort(key=lambda m: parsedate_to_datetime(m[0].get("Date", "")))
    first_hdrs, _ = messages[0]
    description = "<hr>".join(_html_block(h, b) for h, b in messages)
    real_name, sender_email = parseaddr(first_hdrs.get("From", ""))
    sent_at = parsedate_to_datetime(first_hdrs.get("Date", ""))
    return TicketPayload(
        email=sender_email or None,
        name=_decode(real_name).strip() or None,
        subject=_decode(first_hdrs.get("Subject", "")) or "(no subject)",
        description=description,
        group_id=group_id,
        tags=["imported"],
        custom_fields={settings.original_date_field: sent_at.date().isoformat()},
    )


@retry(
    wait=wait_exponential(min=1, max=60),
    stop=stop_after_attempt(5),
    retry=retry_if_exception_type(httpx.HTTPError),
    reraise=True,
)
def push(ticket: TicketPayload) -> None:
    """Create one ticket with retries and back-off."""
    url = f"https://{settings.fd_domain}.freshdesk.com/api/v2/tickets"
    httpx.post(url, auth=(settings.fd_key, "X"), json=ticket.model_dump(exclude_none=True)).raise_for_status()


def _init_db(purge: bool) -> sqlite3.Connection:
    """Initialize or purge the progress database."""
    conn = sqlite3.connect(_DB_PATH)
    cur = conn.cursor()
    if purge:
        cur.execute("DROP TABLE IF EXISTS processed")
    cur.execute("CREATE TABLE IF NOT EXISTS processed(thread_id TEXT PRIMARY KEY)")
    conn.commit()
    return conn


def _handle_interrupt(signum, frame) -> None:
    """Catch SIGINT to exit cleanly."""
    raise KeyboardInterrupt


def sync() -> None:
    """Main driver with SQLite resume, progress bar and duplicate avoidance."""
    signal.signal(signal.SIGINT, _handle_interrupt)
    purge = input("Purge progress database? [y/N]: ").strip().lower() == "y"
    conn = _init_db(purge)
    cur = conn.cursor()
    ensure_custom_field()
    group_id = ensure_import_group()
    items: list[tuple[str, dict, str]] = []
    for headers, body in iter_messages(settings.mbox_path):
        if _is_spam(headers):
            continue
        tid = str(headers.get("X-GM-THRID") or headers.get("Message-ID") or id(headers))
        cur.execute("SELECT 1 FROM processed WHERE thread_id = ?", (tid,))
        if cur.fetchone():
            continue
        items.append((tid, headers, body))
    if not items:
        print("Nothing new to import")
        return
    iterator = items
    if tqdm:
        iterator = tqdm(items, desc="Importing threads", unit="thread")
    try:
        for tid, hdrs, body in iterator:
            push(build_thread_ticket([(hdrs, body)], group_id))
            cur.execute(  # type: ignore
                "INSERT OR IGNORE INTO processed(thread_id) VALUES (?)", (tid,)
            )
            conn.commit()
            time.sleep(settings.rate_delay)
    except KeyboardInterrupt:
        conn.commit()
        print("\nInterrupted — progress saved. Re-run to resume.")
        sys.exit(1)
    conn.close()
    _DB_PATH.unlink(missing_ok=True)
    print("Import complete without duplicates")


