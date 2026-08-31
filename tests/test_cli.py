"""The CLI seam: argument precedence over environment, exit codes, and
error messages that carry variable names instead of tracebacks."""

import os

import pytest
from imap_tools.errors import MailboxLoginError

from postfach_mcp import cli, config

VALID_ENV = {
    "IMAP_HOST": "imap.example.org",
    "IMAP_USER": "user@example.org",
    "IMAP_PASSWORD": "secret-password",
    "TOKEN": "t" * 32,
}


@pytest.fixture
def clean_env(monkeypatch):
    """Remove every POSTFACH_MCP_* variable so tests start from nothing."""
    for name in list(os.environ):
        if name.startswith(config.PREFIX):
            monkeypatch.delenv(name)
    return monkeypatch


@pytest.fixture
def valid_env(clean_env):
    for name, value in VALID_ENV.items():
        clean_env.setenv(config.PREFIX + name, value)
    return clean_env


@pytest.fixture
def uvicorn_calls(monkeypatch):
    """Record uvicorn.run invocations instead of starting a server."""
    calls: list[dict] = []
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, **kwargs: calls.append(kwargs))
    return calls


# -- serve --


def test_serve_uses_environment(valid_env, uvicorn_calls):
    valid_env.setenv(config.PREFIX + "PORT", "9001")
    assert cli.main(["serve"]) == 0
    assert uvicorn_calls == [{"host": "127.0.0.1", "port": 9001, "log_level": "info"}]


def test_serve_flags_override_environment(valid_env, uvicorn_calls):
    valid_env.setenv(config.PREFIX + "PORT", "9001")
    assert cli.main(["serve", "--host", "0.0.0.0", "--port", "9002"]) == 0
    assert uvicorn_calls[0]["host"] == "0.0.0.0"
    assert uvicorn_calls[0]["port"] == 9002


def test_serve_config_error_exits_without_traceback(clean_env, uvicorn_calls, capsys):
    assert cli.main(["serve"]) == 1
    captured = capsys.readouterr()
    assert config.PREFIX + "IMAP_HOST" in captured.err
    assert "Traceback" not in captured.err
    assert uvicorn_calls == []


# -- check --


def test_check_lists_folders_and_marks_drafts(valid_env, fake_mailbox, capsys):
    valid_env.delenv(config.PREFIX + "TOKEN")  # check must not require a token
    fake_mailbox.add_folder("Drafts")
    fake_mailbox.add_folder("Archive")
    assert cli.main(["check"]) == 0
    out = capsys.readouterr().out
    assert "login ok: user@example.org at imap.example.org:993" in out
    assert "Archive" in out
    assert "Drafts  (drafts folder)" in out


def test_check_missing_drafts_folder_fails(valid_env, fake_mailbox, capsys):
    valid_env.setenv(config.PREFIX + "DRAFTS_FOLDER", "Entwürfe")
    assert cli.main(["check"]) == 1
    err = capsys.readouterr().err
    assert "'Entwürfe'" in err
    assert config.PREFIX + "DRAFTS_FOLDER" in err


def test_check_login_failure_stays_credential_free(valid_env, fake_mailbox, capsys):
    fake_mailbox.login_error = MailboxLoginError(("NO", [b"LOGIN failed"]), "OK")
    assert cli.main(["check"]) == 1
    err = capsys.readouterr().err
    assert "login failed" in err
    assert "secret-password" not in err
    assert "Traceback" not in err
