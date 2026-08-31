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
from collections.abc import Iterator
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
