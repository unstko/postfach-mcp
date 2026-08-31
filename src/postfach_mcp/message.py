"""Pure conversion between MIME messages and tool-friendly structures.

No network, no state — everything here is a function from values to values,
which is what makes the interesting logic of this server trivially testable.

Two security properties live here and must survive any refactoring:

- Incoming mail is untrusted input. It is only ever copied into structured
  return fields, never interpreted.
- Outgoing draft headers are built exclusively from validated values;
  `ensure_header_safe` rejects CR/LF and control characters, so header
  injection through tool arguments is not possible.
"""

from __future__ import annotations

import re
from email.headerregistry import Address
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr
from html.parser import HTMLParser
from typing import Any

MAX_BODY_CHARS = 50_000

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def ensure_header_safe(value: str, field: str) -> str:
    """Reject values that could smuggle extra headers into a message."""
    if _CONTROL_CHARS.search(value):
        raise ValueError(f"invalid characters in header field '{field}'")
    return value


def parse_address(raw: str, field: str) -> Address:
    """Parse 'Name <user@host>' or a bare address, rejecting anything odd."""
    ensure_header_safe(raw, field)
    name, addr = parseaddr(raw)
    if not addr or "@" not in addr:
        raise ValueError(f"invalid email address in '{field}': {raw!r}")
    try:
        return Address(display_name=name, addr_spec=addr)
    except (ValueError, IndexError) as err:
        raise ValueError(f"invalid email address in '{field}': {raw!r}") from err


# -- Reading ----------------------------------------------------------------


class _TextExtractor(HTMLParser):
    """HTML to plain text: block tags become line breaks, script/style
    content is dropped, link targets stay visible next to their text so a
    reader (human or model) can spot where a link really points."""

    BLOCK = {
        "p", "div", "br", "li", "ul", "ol", "tr", "table",
        "blockquote", "h1", "h2", "h3", "h4", "h5", "h6",
    }  # fmt: skip
    SKIP = {"script", "style", "head", "title", "template"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip_depth = 0
        self._href: str | None = None
        self._link_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.SKIP:
            self._skip_depth += 1
            return
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._link_text = []
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag == "a":
            text = "".join(self._link_text).strip()
            href = self._href or ""
            self._href = None
            if href and href not in text and not href.startswith("#"):
                self.parts.append(f" ({href})")
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._href is not None:
            self._link_text.append(data)
        self.parts.append(data)


def html_to_text(html: str) -> str:
    extractor = _TextExtractor()
    extractor.feed(html)
    extractor.close()
    text = "".join(extractor.parts).replace("\xa0", " ")
    lines = [line.strip() for line in text.splitlines()]
    collapsed = re.sub(r"\n{3,}", "\n\n", "\n".join(lines))
    return collapsed.strip()


def _header(msg: Any, name: str) -> str | None:
    values = msg.headers.get(name.lower()) or ()
    return values[0].strip() if values else None


def _sender(msg: Any) -> str:
    values = getattr(msg, "from_values", None)
    return values.full if values else msg.from_


def threading_headers(msg: Any) -> tuple[str | None, list[str]]:
    """In-Reply-To and References for a reply to `msg`, per RFC 5322:
    the parent's Message-ID becomes In-Reply-To and is appended to the
    parent's References chain."""
    message_id = _header(msg, "message-id")
    if not message_id:
        return None, []
    parent_refs = _header(msg, "references")
    return message_id, (parent_refs.split() if parent_refs else []) + [message_id]


def summarize(msg: Any) -> dict[str, Any]:
    """The list/search view: enough to decide whether to read a message."""
    return {
        "uid": str(msg.uid),
        "date": msg.date.isoformat() if msg.date else None,
        "from": _sender(msg),
        "subject": msg.subject,
        "seen": "\\Seen" in msg.flags,
        "size": msg.size,
    }


def full(msg: Any, folder: str, max_body_chars: int = MAX_BODY_CHARS) -> dict[str, Any]:
    """The reading view: headers, one body text, attachment metadata only."""
    body = msg.text or ""
    source = "text"
    if not body.strip() and (msg.html or "").strip():
        body = html_to_text(msg.html)
        source = "html_converted"
    truncated = len(body) > max_body_chars
    references = _header(msg, "references")
    return {
        "uid": str(msg.uid),
        "folder": folder,
        "date": msg.date.isoformat() if msg.date else None,
        "from": _sender(msg),
        "to": list(msg.to),
        "cc": list(msg.cc),
        "reply_to": list(msg.reply_to),
        "subject": msg.subject,
        "message_id": _header(msg, "message-id"),
        "in_reply_to": _header(msg, "in-reply-to"),
        "references": references.split() if references else [],
        "body": {
            "source": source,
            "text": body[:max_body_chars],
            "truncated": truncated,
        },
        "attachments": [
            {"filename": a.filename, "content_type": a.content_type, "size": a.size}
            for a in msg.attachments
        ],
        "seen": "\\Seen" in msg.flags,
    }


# -- Writing ----------------------------------------------------------------


def build_draft(
    *,
    from_address: str,
    to: list[str],
    subject: str,
    body: str,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    in_reply_to: str | None = None,
    references: list[str] | None = None,
) -> EmailMessage:
    """Build an RFC-822 draft. Threading headers are the caller's choice;
    Message-ID and Date are always set so the draft is complete."""
    msg = EmailMessage()
    msg["From"] = parse_address(from_address, "from")
    msg["To"] = [parse_address(raw, "to") for raw in to]
    if cc:
        msg["Cc"] = [parse_address(raw, "cc") for raw in cc]
    if bcc:
        msg["Bcc"] = [parse_address(raw, "bcc") for raw in bcc]
    msg["Subject"] = ensure_header_safe(subject, "subject")
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid()
    if in_reply_to:
        msg["In-Reply-To"] = ensure_header_safe(in_reply_to, "in_reply_to")
    if references:
        msg["References"] = " ".join(ensure_header_safe(ref, "references") for ref in references)
    msg.set_content(body)
    return msg
