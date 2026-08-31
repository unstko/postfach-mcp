"""Settings from environment variables.

Everything the server needs to know about its environment is set from the
outside, nothing is hard-coded: the same binary serves local testing and a
locked-down production host. Missing variables are collected and reported
together, so one restart fixes the whole list instead of one name at a time.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

PREFIX = "POSTFACH_MCP_"

# A shorter token is a guessable token. The error message tells the operator
# how to generate a proper one, so the limit never turns into a puzzle.
MIN_TOKEN_LENGTH = 32


class ConfigError(Exception):
    """The environment is missing a variable or carries an unusable value."""


@dataclass(frozen=True)
class Account:
    """One IMAP account. Tools receive an Account, never the full Settings,
    so a later multi-account version only has to change how accounts are
    looked up, not how they are used."""

    imap_host: str
    imap_port: int
    user: str
    password: str
    drafts_folder: str
    from_address: str
    # "text" writes plain-text drafts; "html" adds an HTML alternative for
    # clients whose composer collapses plain-text line breaks (e.g. Spark).
    draft_format: str


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    token: str | None
    allowed_hosts: tuple[str, ...]
    account: Account


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(f"{PREFIX}{name}")
    return value if value not in (None, "") else default


def _int(name: str, default: str, problems: list[str]) -> int:
    """Read a number — naming the variable when it is not one.

    A bare ValueError would hide which of the variables is broken.
    """
    raw = _env(name, default)
    assert raw is not None
    try:
        return int(raw)
    except ValueError:
        problems.append(f"{PREFIX}{name} must be a number, not {raw!r}")
        return 0


def _hosts(raw: str | None) -> tuple[str, ...]:
    """Comma-separated host names; whitespace and empty entries are dropped."""
    if not raw:
        return ()
    return tuple(part.strip().lower() for part in raw.split(",") if part.strip())


def load(require_token: bool = True) -> Settings:
    """Read settings, reporting every problem at once.

    `require_token` is False for commands that never open the HTTP side
    (like the connection check), so a missing token does not block them.
    """
    problems: list[str] = []

    required = {}
    for name in ("IMAP_HOST", "IMAP_USER", "IMAP_PASSWORD"):
        value = _env(name)
        if value is None:
            problems.append(f"{PREFIX}{name} is not set")
        required[name] = value or ""

    token = _env("TOKEN")
    if require_token:
        if token is None:
            problems.append(f"{PREFIX}TOKEN is not set (generate one with: openssl rand -hex 32)")
        elif len(token) < MIN_TOKEN_LENGTH:
            problems.append(
                f"{PREFIX}TOKEN must be at least {MIN_TOKEN_LENGTH} characters "
                "(generate one with: openssl rand -hex 32)"
            )

    imap_port = _int("IMAP_PORT", "993", problems)
    port = _int("PORT", "8000", problems)

    draft_format = _env("DRAFT_FORMAT", "text") or "text"
    if draft_format not in ("text", "html"):
        problems.append(f"{PREFIX}DRAFT_FORMAT must be 'text' or 'html', not {draft_format!r}")

    if problems:
        raise ConfigError("; ".join(problems))

    user = required["IMAP_USER"]
    return Settings(
        host=_env("HOST", "127.0.0.1") or "127.0.0.1",
        port=port,
        token=token,
        allowed_hosts=_hosts(_env("ALLOWED_HOSTS", "127.0.0.1,localhost")),
        account=Account(
            imap_host=required["IMAP_HOST"],
            imap_port=imap_port,
            user=user,
            password=required["IMAP_PASSWORD"],
            drafts_folder=_env("DRAFTS_FOLDER", "Drafts") or "Drafts",
            from_address=_env("FROM_ADDRESS", user) or user,
            draft_format=draft_format,
        ),
    )
