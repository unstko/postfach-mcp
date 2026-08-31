import pytest

from postfach_mcp import config

VALID = {
    "IMAP_HOST": "imap.example.org",
    "IMAP_USER": "user@example.org",
    "IMAP_PASSWORD": "secret",
    "TOKEN": "t" * 32,
}


@pytest.fixture
def clean_env(monkeypatch):
    """Remove every POSTFACH_MCP_* variable so tests start from nothing."""
    import os

    for name in list(os.environ):
        if name.startswith(config.PREFIX):
            monkeypatch.delenv(name)
    return monkeypatch


def set_valid(monkeypatch, **overrides):
    values = {**VALID, **overrides}
    for name, value in values.items():
        if value is None:
            continue
        monkeypatch.setenv(config.PREFIX + name, value)


def test_load_with_all_required(clean_env):
    set_valid(clean_env)
    settings = config.load()
    assert settings.host == "127.0.0.1"
    assert settings.port == 8000
    assert settings.token == "t" * 32
    assert settings.allowed_hosts == ("127.0.0.1", "localhost")
    assert settings.account.imap_host == "imap.example.org"
    assert settings.account.imap_port == 993
    assert settings.account.user == "user@example.org"
    assert settings.account.password == "secret"
    assert settings.account.drafts_folder == "Drafts"


def test_missing_host_names_the_variable(clean_env):
    set_valid(clean_env, IMAP_HOST=None)
    clean_env.delenv(config.PREFIX + "IMAP_HOST", raising=False)
    with pytest.raises(config.ConfigError, match="POSTFACH_MCP_IMAP_HOST"):
        config.load()


def test_all_missing_variables_reported_together(clean_env):
    with pytest.raises(config.ConfigError) as excinfo:
        config.load()
    message = str(excinfo.value)
    for name in ("IMAP_HOST", "IMAP_USER", "IMAP_PASSWORD", "TOKEN"):
        assert config.PREFIX + name in message


def test_non_numeric_port_names_the_variable(clean_env):
    set_valid(clean_env, PORT="eight thousand")
    with pytest.raises(config.ConfigError, match="POSTFACH_MCP_PORT"):
        config.load()


def test_short_token_rejected_with_hint(clean_env):
    set_valid(clean_env, TOKEN="short")
    with pytest.raises(config.ConfigError, match="openssl rand"):
        config.load()


def test_token_not_required_when_disabled(clean_env):
    set_valid(clean_env, TOKEN=None)
    settings = config.load(require_token=False)
    assert settings.token is None


def test_allowed_hosts_parsing(clean_env):
    set_valid(clean_env, ALLOWED_HOSTS=" Mail.example.org , ,localhost ")
    settings = config.load()
    assert settings.allowed_hosts == ("mail.example.org", "localhost")


def test_from_address_defaults_to_user(clean_env):
    set_valid(clean_env)
    assert config.load().account.from_address == "user@example.org"


def test_from_address_override(clean_env):
    set_valid(clean_env, FROM_ADDRESS="Stefan <s@example.org>")
    assert config.load().account.from_address == "Stefan <s@example.org>"


def test_draft_format_defaults_to_text(clean_env):
    set_valid(clean_env)
    assert config.load().account.draft_format == "text"


def test_draft_format_html(clean_env):
    set_valid(clean_env, DRAFT_FORMAT="html")
    assert config.load().account.draft_format == "html"


def test_draft_format_rejects_unknown_value(clean_env):
    set_valid(clean_env, DRAFT_FORMAT="markdown")
    with pytest.raises(config.ConfigError, match="POSTFACH_MCP_DRAFT_FORMAT"):
        config.load()


def test_custom_ports_and_folder(clean_env):
    set_valid(clean_env, IMAP_PORT="143", PORT="9999", DRAFTS_FOLDER="Entwürfe")
    settings = config.load()
    assert settings.account.imap_port == 143
    assert settings.port == 9999
    assert settings.account.drafts_folder == "Entwürfe"
