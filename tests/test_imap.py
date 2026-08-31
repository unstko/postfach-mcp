import pytest
from imap_tools.errors import MailboxLoginError, MailboxMoveError

from postfach_mcp import imap


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
