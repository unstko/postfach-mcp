"""The only module that touches the network.

Every tool call opens a fresh connection and closes it afterwards. That
costs a few hundred milliseconds of login per call — negligible for an
interactive assistant — and buys the robustness a pooled connection would
have to earn with reconnect logic: imap-tools has none, and IMAP servers
drop idle connections within minutes.

All imap-tools and socket errors are translated into ImapError with a
one-sentence message that is safe to show an MCP client: server responses
may appear in it, credentials never do.
"""

from __future__ import annotations

import imaplib
from collections.abc import Iterator, Sequence
from contextlib import contextmanager

from imap_tools import MailBox
from imap_tools.errors import (
    ImapToolsError,
    MailboxFolderSelectError,
    MailboxLoginError,
)

from .config import Account

# Applies to connect and to every socket operation afterwards. Without it a
# stalled server would hang a tool call indefinitely.
TIMEOUT_SECONDS = 30.0


class ImapError(Exception):
    """An IMAP operation failed; the message is safe to pass to the client."""


@contextmanager
def open_mailbox(account: Account, folder: str | None = None) -> Iterator[MailBox]:
    """Connect, log in, select `folder` (INBOX by default), always log out."""
    try:
        box = MailBox(account.imap_host, account.imap_port, timeout=TIMEOUT_SECONDS)
    except (OSError, imaplib.IMAP4.error) as err:
        raise ImapError(
            f"IMAP server unreachable: {account.imap_host}:{account.imap_port}"
        ) from err

    try:
        try:
            box.login(account.user, account.password, initial_folder=folder or "INBOX")
        except MailboxLoginError as err:
            # Deliberately without the server response: some servers echo
            # parts of the login command in it.
            raise ImapError("IMAP login failed (check credentials)") from err
        except MailboxFolderSelectError as err:
            raise ImapError(f"folder not found: {folder}") from err

        try:
            yield box
        except ImapError:
            raise
        except MailboxFolderSelectError as err:
            raise ImapError("folder not found") from err
        except (ImapToolsError, imaplib.IMAP4.error, OSError) as err:
            raise ImapError(f"IMAP operation failed: {err}") from err
    finally:
        try:
            box.logout()
        except Exception:
            # Logout is best effort; the interesting error already happened.
            pass


def expand_sequence_set(sequence_set: str) -> list[str]:
    """Expand an IMAP sequence-set like '3:5,8' into individual uids."""
    uids: list[str] = []
    for part in sequence_set.split(","):
        first, colon, last = part.partition(":")
        if not colon:
            if not first.isdigit():
                raise ValueError(f"invalid sequence set: {sequence_set!r}")
            uids.append(first)
            continue
        if not (first.isdigit() and last.isdigit()):
            raise ValueError(f"invalid sequence set: {sequence_set!r}")
        # RFC 3501 allows either order of the range ends.
        lo, hi = sorted((int(first), int(last)))
        uids.extend(str(n) for n in range(lo, hi + 1))
    return uids


def parse_copyuid(datas: Sequence[bytes | None]) -> dict[str, str] | None:
    """COPYUID response data ('<uidvalidity> <source-set> <dest-set>') as a
    source-uid → destination-uid mapping.

    Sets correspond pairwise only within one COPYUID entry (RFC 4315), so
    each entry is expanded and zipped on its own before merging. Returns
    None when there was no COPYUID or the data does not parse — the move
    itself succeeded either way, and no mapping beats a wrong one."""
    uid_map: dict[str, str] = {}
    for data in datas:
        if data is None:
            continue
        try:
            _validity, source_set, dest_set = data.decode("ascii").split()
            sources = expand_sequence_set(source_set)
            destinations = expand_sequence_set(dest_set)
        except ValueError:
            return None
        if len(sources) != len(destinations):
            return None
        uid_map.update(zip(sources, destinations, strict=True))
    return uid_map or None


def move_with_uid_map(mb: MailBox, uids: Sequence[str], to_folder: str) -> dict[str, str] | None:
    """Move messages and report where they landed, if the server says.

    UIDPLUS servers announce the new uids in a COPYUID response code, which
    imaplib collects under that key for tagged (COPY) and untagged (MOVE)
    responses alike — and pops on read, so it is read exactly once here."""
    mb.move(list(uids), to_folder)
    datas: Sequence[bytes | None] = mb.client.response("COPYUID")[1]
    return parse_copyuid(datas)
