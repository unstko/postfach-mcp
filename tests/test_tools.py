import asyncio
import dataclasses
from email import message_from_bytes, policy
from typing import Any

import pytest
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult

from postfach_mcp import config, tools
from tests.conftest import FakeMessage


@pytest.fixture
def settings(account) -> config.Settings:
    return config.Settings(
        host="127.0.0.1",
        port=8000,
        token="t" * 32,
        allowed_hosts=("127.0.0.1",),
        account=account,
    )


@pytest.fixture
def server(settings, fake_mailbox) -> MCPServer:
    mcp = MCPServer("postfach-mcp-test")
    tools.register(mcp, settings)
    return mcp


def call(server: MCPServer, tool_name: str, **args: Any) -> dict[str, Any]:
    result = asyncio.run(server.call_tool(tool_name, args))
    assert isinstance(result, CallToolResult)
    assert result.is_error is False
    assert result.structured_content is not None
    return result.structured_content


def call_error(server: MCPServer, tool_name: str, match: str, **args: Any) -> None:
    with pytest.raises(ToolError, match=match):
        asyncio.run(server.call_tool(tool_name, args))


def last_call(box, kind: str) -> dict[str, Any]:
    return [c for c in box.calls if c[0] == kind][-1][1]


class TestListFolders:
    def test_umlaut_folder_and_noselect(self, server, fake_mailbox):
        fake_mailbox.add_folder("Entwürfe")
        fake_mailbox.add_folder("[Gmail]", flags=("\\Noselect",))
        result = call(server, "list_folders")
        by_name = {f["name"]: f for f in result["folders"]}
        assert by_name["Entwürfe"]["selectable"] is True
        assert by_name["[Gmail]"]["selectable"] is False

    def test_without_counts_stays_lean(self, server, fake_mailbox):
        fake_mailbox.add_folder("Archive")
        result = call(server, "list_folders")
        assert "messages" not in result["folders"][0]
        assert not [c for c in fake_mailbox.calls if c[0] == "folder.status"]

    def test_with_counts_over_one_connection(self, server, fake_mailbox):
        fake_mailbox.add_message("INBOX", FakeMessage(uid="1", flags=("\\Seen",)))
        fake_mailbox.add_message("INBOX", FakeMessage(uid="2"))
        fake_mailbox.add_folder("Archive")
        fake_mailbox.add_folder("[Gmail]", flags=("\\Noselect",))
        result = call(server, "list_folders", with_counts=True)
        by_name = {f["name"]: f for f in result["folders"]}
        assert by_name["INBOX"]["messages"] == 2
        assert by_name["INBOX"]["unseen"] == 1
        assert by_name["Archive"]["messages"] == 0
        # Noselect folders get no STATUS call and no count keys.
        assert "messages" not in by_name["[Gmail]"]
        status_calls = [c for c in fake_mailbox.calls if c[0] == "folder.status"]
        assert [c[1]["folder"] for c in status_calls] == ["INBOX", "Archive"]
        assert len([c for c in fake_mailbox.calls if c[0] == "connect"]) == 1


class TestFolderStatus:
    def test_counts(self, server, fake_mailbox):
        fake_mailbox.add_message("INBOX", FakeMessage(uid="1", flags=("\\Seen",)))
        fake_mailbox.add_message("INBOX", FakeMessage(uid="2"))
        assert call(server, "folder_status") == {"folder": "INBOX", "messages": 2, "unseen": 1}

    def test_unknown_folder(self, server, fake_mailbox):
        call_error(server, "folder_status", "folder not found: Nope", folder="Nope")


class TestListMessages:
    def test_empty_folder(self, server, fake_mailbox):
        result = call(server, "list_messages")
        assert result == {"folder": "INBOX", "count": 0, "messages": []}

    def test_newest_first_and_never_marks_seen(self, server, fake_mailbox):
        fake_mailbox.add_message("INBOX", FakeMessage(uid="1", subject="old"))
        fake_mailbox.add_message("INBOX", FakeMessage(uid="2", subject="new"))
        result = call(server, "list_messages")
        assert [m["subject"] for m in result["messages"]] == ["new", "old"]
        fetch = last_call(fake_mailbox, "fetch")
        assert fetch["mark_seen"] is False
        assert fetch["headers_only"] is True

    def test_limit_is_clamped(self, server, fake_mailbox):
        call(server, "list_messages", limit=500)
        assert last_call(fake_mailbox, "fetch")["limit"] == tools.MAX_LIMIT

    def test_unseen_only_criteria(self, server, fake_mailbox):
        call(server, "list_messages", unseen_only=True)
        assert str(last_call(fake_mailbox, "fetch")["criteria"]) == "(UNSEEN)"


class TestSearchMessages:
    def test_requires_a_criterion(self, server, fake_mailbox):
        call_error(server, "search_messages", "at least one search criterion")

    def test_invalid_date(self, server, fake_mailbox):
        call_error(server, "search_messages", "YYYY-MM-DD", since="gestern")

    def test_criteria_reach_the_server(self, server, fake_mailbox):
        call(
            server,
            "search_messages",
            sender="alice@example.org",
            subject="Rechnung",
            since="2026-08-01",
            unseen_only=True,
        )
        criteria = str(last_call(fake_mailbox, "fetch")["criteria"])
        assert 'FROM "alice@example.org"' in criteria
        assert "SUBJECT" in criteria
        assert "SINCE 1-Aug-2026" in criteria
        assert "UNSEEN" in criteria
        # ASCII criteria stay ASCII: no CHARSET surprise for old servers.
        assert last_call(fake_mailbox, "fetch")["charset"] == "US-ASCII"

    def test_non_ascii_criteria_switch_to_utf8(self, server, fake_mailbox):
        call(server, "search_messages", subject="Grüße")
        fetch = last_call(fake_mailbox, "fetch")
        assert fetch["charset"] == "UTF-8"
        assert "Grüße" in str(fetch["criteria"])

    def test_header_existence_is_a_criterion_on_its_own(self, server, fake_mailbox):
        call(server, "search_messages", header_name="List-Unsubscribe")
        fetch = last_call(fake_mailbox, "fetch")
        assert 'HEADER "List-Unsubscribe" ""' in str(fetch["criteria"])
        assert fetch["charset"] == "US-ASCII"

    def test_header_with_value(self, server, fake_mailbox):
        call(server, "search_messages", header_name="X-Spam-Flag", header_value="YES")
        assert 'HEADER "X-Spam-Flag" "YES"' in str(last_call(fake_mailbox, "fetch")["criteria"])

    def test_non_ascii_header_value_switches_to_utf8(self, server, fake_mailbox):
        call(server, "search_messages", header_name="X-Note", header_value="Grüße")
        assert last_call(fake_mailbox, "fetch")["charset"] == "UTF-8"

    def test_header_value_without_name_rejected(self, server, fake_mailbox):
        call_error(server, "search_messages", "header_name", header_value="YES")

    def test_header_injection_rejected(self, server, fake_mailbox):
        call_error(
            server, "search_messages", "invalid characters",
            header_name="X-Evil\r\nA1 DELETE INBOX",
        )  # fmt: skip
        assert not [c for c in fake_mailbox.calls if c[0] == "fetch"]


class TestListHeaders:
    def test_empty_folder_skips_the_fetch(self, server, fake_mailbox):
        result = call(server, "list_headers")
        assert result == {"folder": "INBOX", "total": 0, "offset": 0, "count": 0, "messages": []}
        # An empty uid_list would make imap-tools search the whole folder.
        assert not [c for c in fake_mailbox.calls if c[0] == "fetch"]

    def test_pages_oldest_first_with_numeric_order(self, server, fake_mailbox):
        for uid in ["10", "2", "1", "5", "3"]:
            fake_mailbox.add_message("INBOX", FakeMessage(uid=uid, subject=f"m{uid}"))
        result = call(server, "list_headers", offset=2, limit=2)
        assert result["total"] == 5
        assert result["count"] == 2
        assert [m["uid"] for m in result["messages"]] == ["3", "5"]
        fetch = last_call(fake_mailbox, "fetch")
        assert fetch["mark_seen"] is False
        assert fetch["headers_only"] is True
        assert fetch["bulk"] is True

    def test_offset_beyond_total(self, server, fake_mailbox):
        fake_mailbox.add_message("INBOX", FakeMessage(uid="1"))
        result = call(server, "list_headers", offset=5)
        assert result["total"] == 1
        assert result["count"] == 0
        assert not [c for c in fake_mailbox.calls if c[0] == "fetch"]

    def test_negative_offset_rejected(self, server, fake_mailbox):
        call_error(server, "list_headers", "negative", offset=-1)

    def test_limit_is_clamped_to_500(self, server, fake_mailbox):
        for n in range(510):
            fake_mailbox.add_message("INBOX", FakeMessage(uid=str(n + 1)))
        result = call(server, "list_headers", limit=9999)
        assert result["count"] == 500
        assert len(last_call(fake_mailbox, "fetch")["uid_list"]) == 500

    def test_extra_headers_are_picked(self, server, fake_mailbox):
        fake_mailbox.add_message(
            "INBOX",
            FakeMessage(uid="1", headers={"list-unsubscribe": ("<mailto:u@example.org>",)}),
        )
        fake_mailbox.add_message("INBOX", FakeMessage(uid="2"))
        result = call(server, "list_headers", extra_headers=["List-Unsubscribe"])
        first, second = result["messages"]
        assert first["headers"] == {"List-Unsubscribe": ["<mailto:u@example.org>"]}
        assert second["headers"] == {}

    def test_no_headers_key_without_extra_headers(self, server, fake_mailbox):
        fake_mailbox.add_message("INBOX", FakeMessage(uid="1"))
        result = call(server, "list_headers")
        assert "headers" not in result["messages"][0]


class TestGetMessage:
    def test_reads_without_marking_seen(self, server, fake_mailbox):
        fake_mailbox.add_message("INBOX", FakeMessage(uid="5", subject="Hallo", text="Inhalt"))
        result = call(server, "get_message", folder="INBOX", uid="5")
        assert result["subject"] == "Hallo"
        assert result["folder"] == "INBOX"
        assert result["body"]["text"] == "Inhalt"
        assert last_call(fake_mailbox, "fetch")["mark_seen"] is False

    def test_unknown_uid(self, server, fake_mailbox):
        call_error(
            server, "get_message", "message not found: uid 99 in folder INBOX",
            folder="INBOX", uid="99",
        )  # fmt: skip


class TestCreateDraft:
    def test_draft_lands_in_drafts_folder(self, server, fake_mailbox):
        fake_mailbox.add_folder("Drafts")
        result = call(
            server,
            "create_draft",
            to=["Bob <bob@example.org>"],
            subject="Grüße",
            body="Servus äöü",
        )
        assert result["saved"] is True
        assert result["folder"] == "Drafts"
        raw, folder, flags = fake_mailbox.appended[0]
        assert folder == "Drafts"
        assert set(flags) == {"\\Draft", "\\Seen"}
        parsed = message_from_bytes(raw, policy=policy.default)
        assert parsed["To"] == "Bob <bob@example.org>"
        assert parsed["From"] == "User <user@example.org>"
        assert parsed["Subject"] == "Grüße"
        assert parsed["Message-ID"] == result["message_id"]
        assert "Servus äöü" in parsed.get_content()
        # The APPEND literal must use CRLF line endings (RFC 3501), not
        # rely on the server normalizing bare LF.
        assert b"\r\n" in raw
        assert raw.count(b"\n") == raw.count(b"\r\n")

    def test_html_draft_format_adds_alternative(self, settings, fake_mailbox):
        html_settings = dataclasses.replace(
            settings, account=dataclasses.replace(settings.account, draft_format="html")
        )
        mcp = MCPServer("postfach-mcp-test")
        tools.register(mcp, html_settings)
        fake_mailbox.add_folder("Drafts")
        call(
            mcp,
            "create_draft",
            to=["bob@example.org"],
            subject="Hi",
            body="Absatz eins.\n\nAbsatz zwei.",
        )
        parsed = message_from_bytes(fake_mailbox.appended[0][0], policy=policy.default)
        assert parsed.get_content_type() == "multipart/alternative"
        text_part, html_part = parsed.iter_parts()
        assert text_part.get_content_type() == "text/plain"
        assert "Absatz eins.<br><br>Absatz zwei." in html_part.get_content()

    def test_default_sender_without_from_address(self, server, fake_mailbox):
        fake_mailbox.add_folder("Drafts")
        call(server, "create_draft", to=["bob@example.org"], subject="Hi", body="x")
        parsed = message_from_bytes(fake_mailbox.appended[0][0], policy=policy.default)
        assert parsed["From"] == "User <user@example.org>"

    def test_allowlisted_extra_sender(self, settings, fake_mailbox):
        alt_settings = dataclasses.replace(
            settings,
            account=dataclasses.replace(
                settings.account, from_addresses=("Stefan <koch@gmx.example>",)
            ),
        )
        mcp = MCPServer("postfach-mcp-test")
        tools.register(mcp, alt_settings)
        fake_mailbox.add_folder("Drafts")
        result = call(
            mcp,
            "create_draft",
            to=["bob@example.org"],
            subject="Hi",
            body="x",
            from_address="koch@gmx.example",
        )
        assert result["from"] == "Stefan <koch@gmx.example>"
        parsed = message_from_bytes(fake_mailbox.appended[0][0], policy=policy.default)
        assert parsed["From"] == "Stefan <koch@gmx.example>"
        assert parsed["Message-ID"].endswith("@gmx.example>")

    def test_foreign_sender_rejected(self, server, fake_mailbox):
        fake_mailbox.add_folder("Drafts")
        call_error(
            server, "create_draft", "sender not allowed",
            to=["bob@example.org"], subject="Hi", body="x",
            from_address="attacker@evil.example",
        )  # fmt: skip
        assert fake_mailbox.appended == []

    def test_reply_sets_threading_headers(self, server, fake_mailbox):
        fake_mailbox.add_folder("Drafts")
        fake_mailbox.add_message(
            "INBOX",
            FakeMessage(
                uid="7",
                headers={
                    "message-id": ("<parent@example.org>",),
                    "references": ("<root@example.org>",),
                },
            ),
        )
        call(
            server,
            "create_draft",
            to=["bob@example.org"],
            subject="Re: Thema",
            body="Antwort",
            reply_to_uid="7",
        )
        parsed = message_from_bytes(fake_mailbox.appended[0][0], policy=policy.default)
        assert parsed["In-Reply-To"] == "<parent@example.org>"
        assert parsed["References"] == "<root@example.org> <parent@example.org>"

    def test_reply_original_missing(self, server, fake_mailbox):
        fake_mailbox.add_folder("Drafts")
        call_error(
            server, "create_draft", "message not found: uid 9",
            to=["bob@example.org"], subject="Re: x", body="y", reply_to_uid="9",
        )  # fmt: skip
        assert fake_mailbox.appended == []

    def test_header_injection_never_reaches_append(self, server, fake_mailbox):
        fake_mailbox.add_folder("Drafts")
        call_error(
            server, "create_draft", "invalid characters",
            to=["bob@example.org"], subject="Hi\r\nBcc: hidden@example.org", body="x",
        )  # fmt: skip
        assert fake_mailbox.appended == []
        assert not [c for c in fake_mailbox.calls if c[0] == "append"]

    def test_requires_recipient(self, server, fake_mailbox):
        call_error(server, "create_draft", "at least one recipient", to=[], subject="x", body="y")


class TestFlags:
    def test_mark_read_and_unread(self, server, fake_mailbox):
        fake_mailbox.add_message("INBOX", FakeMessage(uid="3"))
        call(server, "mark_read", folder="INBOX", uids=["3"])
        assert "\\Seen" in fake_mailbox.mailboxes["INBOX"][0].flags
        call(server, "mark_read", folder="INBOX", uids=["3"], seen=False)
        assert "\\Seen" not in fake_mailbox.mailboxes["INBOX"][0].flags

    def test_mark_flagged(self, server, fake_mailbox):
        fake_mailbox.add_message("INBOX", FakeMessage(uid="3"))
        call(server, "mark_flagged", folder="INBOX", uids=["3"])
        assert "\\Flagged" in fake_mailbox.mailboxes["INBOX"][0].flags

    def test_empty_uids_rejected(self, server, fake_mailbox):
        call_error(server, "mark_read", "at least one uid", folder="INBOX", uids=[])

    def test_non_numeric_uid_rejected(self, server, fake_mailbox):
        call_error(server, "mark_read", "numeric", folder="INBOX", uids=["1:*"])


class TestMoveMessages:
    def test_move_and_back(self, server, fake_mailbox):
        fake_mailbox.add_folder("Archive")
        fake_mailbox.add_message("INBOX", FakeMessage(uid="4", subject="weg"))
        result = call(server, "move_messages", folder="INBOX", uids=["4"], to_folder="Archive")
        assert result["moved_to"] == "Archive"
        assert result["uid_map"] is None  # the fake announces no COPYUID by default
        assert fake_mailbox.mailboxes["INBOX"] == []
        assert fake_mailbox.mailboxes["Archive"][0].subject == "weg"

    def test_uid_map_from_copyuid(self, server, fake_mailbox):
        fake_mailbox.add_folder("Archive")
        for uid in ["4", "5", "6"]:
            fake_mailbox.add_message("INBOX", FakeMessage(uid=uid))
        fake_mailbox.copyuid_data = [b"38505 4:6 100:102"]
        result = call(
            server, "move_messages", folder="INBOX", uids=["4", "5", "6"], to_folder="Archive"
        )
        assert result["uid_map"] == {"4": "100", "5": "101", "6": "102"}

    def test_uid_map_merges_chunked_copyuid(self, server, fake_mailbox):
        fake_mailbox.add_folder("Archive")
        for uid in ["4", "9"]:
            fake_mailbox.add_message("INBOX", FakeMessage(uid=uid))
        fake_mailbox.copyuid_data = [b"1 4 100", b"1 9 101"]
        result = call(
            server, "move_messages", folder="INBOX", uids=["4", "9"], to_folder="Archive"
        )
        assert result["uid_map"] == {"4": "100", "9": "101"}

    def test_unknown_target_folder(self, server, fake_mailbox):
        fake_mailbox.add_message("INBOX", FakeMessage(uid="4"))
        call_error(
            server, "move_messages", "folder not found: Nope",
            folder="INBOX", uids=["4"], to_folder="Nope",
        )  # fmt: skip
        assert len(fake_mailbox.mailboxes["INBOX"]) == 1
        assert not [c for c in fake_mailbox.calls if c[0] == "move"]


class TestCreateFolder:
    def test_creates_the_folder(self, server, fake_mailbox):
        result = call(server, "create_folder", name="98_Aussortiert")
        assert result == {"created": True, "folder": "98_Aussortiert"}
        assert "98_Aussortiert" in fake_mailbox.mailboxes
        assert last_call(fake_mailbox, "folder.create") == {"folder": "98_Aussortiert"}

    def test_existing_folder_rejected(self, server, fake_mailbox):
        call_error(server, "create_folder", "already exists", name="INBOX")
        assert not [c for c in fake_mailbox.calls if c[0] == "folder.create"]

    def test_blank_name_rejected(self, server, fake_mailbox):
        call_error(server, "create_folder", "must not be empty", name="   ")
        assert not [c for c in fake_mailbox.calls if c[0] == "folder.create"]
