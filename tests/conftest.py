"""Shared test infrastructure.

Two pillars: a network ban that turns any accidental socket connect into a
test failure, and a FakeMailBox that implements exactly the imap-tools
surface this project uses — recording every call with its keyword
arguments, so tests can assert not only results but how IMAP was asked.
"""

from __future__ import annotations

import socket
from types import SimpleNamespace
from typing import Any

import pytest
from imap_tools.errors import MailboxAppendError, MailboxCopyError, MailboxFolderSelectError

from postfach_mcp import config, imap


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Tests run without network — enforced, not promised."""

    def guard(self, *args, **kwargs):
        raise RuntimeError("network access in tests")

    monkeypatch.setattr(socket.socket, "connect", guard)


@pytest.fixture
def account() -> config.Account:
    return config.Account(
        imap_host="imap.example.org",
        imap_port=993,
        user="user@example.org",
        password="secret-password",
        drafts_folder="Drafts",
        from_address="User <user@example.org>",
    )


class FakeMessage:
    def __init__(
        self,
        uid: str = "1",
        subject: str = "",
        from_: str = "",
        to: tuple[str, ...] = (),
        cc: tuple[str, ...] = (),
        reply_to: tuple[str, ...] = (),
        date: Any = None,
        text: str = "",
        html: str = "",
        flags: tuple[str, ...] = (),
        size: int = 0,
        attachments: tuple[Any, ...] = (),
        headers: dict[str, tuple[str, ...]] | None = None,
    ) -> None:
        self.uid = uid
        self.subject = subject
        self.from_ = from_
        self.from_values = None
        self.to = to
        self.cc = cc
        self.reply_to = reply_to
        self.date = date
        self.text = text
        self.html = html
        self.flags = flags
        self.size = size
        self.attachments = attachments
        self.headers = headers or {}


def fake_attachment(filename: str, content_type: str = "application/pdf", size: int = 1000):
    return SimpleNamespace(filename=filename, content_type=content_type, size=size)


class _FakeFolderManager:
    def __init__(self, box: FakeMailBox) -> None:
        self._box = box

    def list(self):
        self._box.calls.append(("folder.list", {}))
        return [
            SimpleNamespace(name=name, delim="/", flags=self._box.folder_flags.get(name, ()))
            for name in self._box.mailboxes
        ]

    def status(self, folder: str | None = None):
        name = folder or self._box.current_folder
        self._box.calls.append(("folder.status", {"folder": name}))
        if name not in self._box.mailboxes:
            raise MailboxFolderSelectError(("NO", [b"no such folder"]), "OK")
        messages = self._box.mailboxes[name]
        unseen = sum(1 for m in messages if "\\Seen" not in m.flags)
        return {"MESSAGES": len(messages), "UNSEEN": unseen}

    def exists(self, name: str) -> bool:
        self._box.calls.append(("folder.exists", {"folder": name}))
        return name in self._box.mailboxes

    def set(self, name: str):
        self._box.calls.append(("folder.set", {"folder": name}))
        self._box._select(name)


class FakeMailBox:
    """In-memory stand-in for imap_tools.MailBox, one instance per test."""

    def __init__(self) -> None:
        self.mailboxes: dict[str, list[FakeMessage]] = {"INBOX": []}
        self.folder_flags: dict[str, tuple[str, ...]] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.appended: list[tuple[bytes, str, tuple[str, ...]]] = []
        self.current_folder: str | None = None
        self.login_error: Exception | None = None
        self.connect_error: Exception | None = None
        self.logged_out = False
        self.folder = _FakeFolderManager(self)

    # -- test setup helpers --

    def add_folder(self, name: str, flags: tuple[str, ...] = ()) -> None:
        self.mailboxes.setdefault(name, [])
        if flags:
            self.folder_flags[name] = flags

    def add_message(self, folder: str, msg: FakeMessage) -> None:
        self.mailboxes.setdefault(folder, []).append(msg)

    # -- imap_tools surface --

    def login(self, user: str, password: str, initial_folder: str = "INBOX"):
        self.calls.append(("login", {"user": user, "initial_folder": initial_folder}))
        if self.login_error:
            raise self.login_error
        self._select(initial_folder)
        return self

    def logout(self) -> None:
        self.logged_out = True

    def _select(self, folder: str) -> None:
        if folder not in self.mailboxes:
            raise MailboxFolderSelectError(("NO", [b"no such folder"]), "OK")
        self.current_folder = folder

    def fetch(
        self,
        criteria: Any = "ALL",
        charset: str = "US-ASCII",
        *,
        limit: int | None = None,
        reverse: bool = False,
        headers_only: bool = False,
        bulk: bool = False,
        mark_seen: bool = True,
        uid_list: list[str] | None = None,
    ):
        self.calls.append(
            (
                "fetch",
                {
                    "criteria": criteria,
                    "charset": charset,
                    "limit": limit,
                    "reverse": reverse,
                    "headers_only": headers_only,
                    "bulk": bulk,
                    "mark_seen": mark_seen,
                    "uid_list": uid_list,
                },
            )
        )
        assert self.current_folder is not None
        messages = list(self.mailboxes[self.current_folder])
        if uid_list is not None:
            messages = [m for m in messages if m.uid in uid_list]
        if reverse:
            messages.reverse()
        if limit is not None:
            messages = messages[:limit]
        return messages

    def append(
        self,
        message: bytes,
        folder: str = "INBOX",
        dt: Any = None,
        flag_set: Any = None,
    ):
        flags = tuple(flag_set or ())
        self.calls.append(("append", {"folder": folder, "flag_set": flags}))
        if folder not in self.mailboxes:
            raise MailboxAppendError(("NO", [b"TRYCREATE"]), "OK")
        self.appended.append((message, folder, flags))
        return ("OK", [b"APPEND completed"])

    def flag(self, uid_list: list[str], flag: str, value: bool):
        self.calls.append(("flag", {"uid_list": list(uid_list), "flag": flag, "value": value}))
        assert self.current_folder is not None
        for msg in self.mailboxes[self.current_folder]:
            if msg.uid not in uid_list:
                continue
            flags = set(msg.flags)
            flags.add(flag) if value else flags.discard(flag)
            msg.flags = tuple(flags)
        return ("OK", [b"STORE completed"])

    def move(self, uid_list: list[str], destination_folder: str):
        self.calls.append(
            ("move", {"uid_list": list(uid_list), "destination_folder": destination_folder})
        )
        if destination_folder not in self.mailboxes:
            raise MailboxCopyError(("NO", [b"TRYCREATE"]), "OK")
        assert self.current_folder is not None
        source = self.mailboxes[self.current_folder]
        moved = [m for m in source if m.uid in uid_list]
        self.mailboxes[self.current_folder] = [m for m in source if m.uid not in uid_list]
        self.mailboxes[destination_folder].extend(moved)
        return (("OK", [b"COPY"]), ("OK", [b"EXPUNGE"]))


@pytest.fixture
def fake_mailbox(monkeypatch) -> FakeMailBox:
    """Route postfach_mcp.imap through a FakeMailBox instance."""
    box = FakeMailBox()

    def factory(host: str, port: int = 993, timeout: float | None = None):
        box.calls.append(("connect", {"host": host, "port": port, "timeout": timeout}))
        if box.connect_error:
            raise box.connect_error
        return box

    monkeypatch.setattr(imap, "MailBox", factory)
    return box
