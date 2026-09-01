import pytest
from imap_tools.errors import MailboxLoginError, MailboxMoveError

from postfach_mcp import imap
from tests.conftest import FakeMessage


def test_yields_mailbox_and_logs_out(fake_mailbox, account):
    with imap.open_mailbox(account) as mb:
        assert mb is fake_mailbox
        assert fake_mailbox.current_folder == "INBOX"
    assert fake_mailbox.logged_out


def test_selects_requested_folder(fake_mailbox, account):
    fake_mailbox.add_folder("Archive")
    with imap.open_mailbox(account, folder="Archive"):
        assert fake_mailbox.current_folder == "Archive"


def test_login_failure_without_credentials_in_message(fake_mailbox, account):
    fake_mailbox.login_error = MailboxLoginError(("NO", [b"[AUTHENTICATIONFAILED]"]), "OK")
    with pytest.raises(imap.ImapError, match="login failed") as excinfo:
        with imap.open_mailbox(account):
            pass
    assert account.password not in str(excinfo.value)


def test_unknown_initial_folder(fake_mailbox, account):
    with pytest.raises(imap.ImapError, match="folder not found: Nope"):
        with imap.open_mailbox(account, folder="Nope"):
            pass


def test_unreachable_server(fake_mailbox, account):
    fake_mailbox.connect_error = OSError("connection refused")
    with pytest.raises(imap.ImapError, match="unreachable"):
        with imap.open_mailbox(account):
            pass


def test_imap_tools_error_inside_body_is_translated(fake_mailbox, account):
    with pytest.raises(imap.ImapError, match="IMAP operation failed"):
        with imap.open_mailbox(account):
            raise MailboxMoveError(("NO", [b"broken"]), "OK")
    assert fake_mailbox.logged_out


def test_imap_error_from_body_passes_through(fake_mailbox, account):
    with pytest.raises(imap.ImapError, match="custom"):
        with imap.open_mailbox(account):
            raise imap.ImapError("custom")


class TestExpandSequenceSet:
    def test_range_and_single(self):
        assert imap.expand_sequence_set("3:5,8") == ["3", "4", "5", "8"]

    def test_single_value(self):
        assert imap.expand_sequence_set("7") == ["7"]

    def test_mixed(self):
        assert imap.expand_sequence_set("1,3:4,9") == ["1", "3", "4", "9"]

    def test_inverted_range(self):
        # RFC 3501 allows either order of the range ends.
        assert imap.expand_sequence_set("5:3") == ["3", "4", "5"]

    def test_non_numeric_rejected(self):
        with pytest.raises(ValueError, match="sequence set"):
            imap.expand_sequence_set("1:*")


class TestParseCopyuid:
    def test_absent(self):
        assert imap.parse_copyuid([None]) is None

    def test_single_entry(self):
        result = imap.parse_copyuid([b"38505 3:5,8 100:103"])
        assert result == {"3": "100", "4": "101", "5": "102", "8": "103"}

    def test_chunked_entries_are_merged(self):
        # Correspondence holds per entry, so each is zipped on its own.
        result = imap.parse_copyuid([b"1 1:2 10:11", b"1 5 12"])
        assert result == {"1": "10", "2": "11", "5": "12"}

    def test_length_mismatch_yields_none(self):
        assert imap.parse_copyuid([b"1 1:3 10:11"]) is None

    def test_garbage_yields_none(self):
        assert imap.parse_copyuid([b"not copyuid data"]) is None


class TestMoveWithUidMap:
    def test_reports_mapping(self, fake_mailbox, account):
        fake_mailbox.add_folder("Archive")
        fake_mailbox.add_message("INBOX", FakeMessage(uid="4"))
        fake_mailbox.copyuid_data = [b"1 4 100"]
        with imap.open_mailbox(account) as mb:
            assert imap.move_with_uid_map(mb, ["4"], "Archive") == {"4": "100"}

    def test_without_uidplus(self, fake_mailbox, account):
        fake_mailbox.add_folder("Archive")
        fake_mailbox.add_message("INBOX", FakeMessage(uid="4"))
        with imap.open_mailbox(account) as mb:
            assert imap.move_with_uid_map(mb, ["4"], "Archive") is None

    def test_reads_the_response_exactly_once(self, fake_mailbox, account):
        fake_mailbox.add_folder("Archive")
        fake_mailbox.add_message("INBOX", FakeMessage(uid="4"))
        fake_mailbox.copyuid_data = [b"1 4 100"]
        with imap.open_mailbox(account) as mb:
            imap.move_with_uid_map(mb, ["4"], "Archive")
            # imaplib pops response codes on read; a second read is empty.
            assert fake_mailbox.client.response("COPYUID") == ("COPYUID", [None])
