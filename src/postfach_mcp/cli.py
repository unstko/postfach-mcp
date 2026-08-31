"""Command line entry point.

Two commands: `serve` runs the HTTP server, `check` probes the IMAP login
and prints the folder list — the deploy diagnosis that answers "are the
credentials right, and what is the drafts folder actually called?" without
starting the server. Configuration errors exit with the collected message
and no traceback: the operator needs variable names, not a stack.
"""

from __future__ import annotations

import argparse
import sys

import uvicorn

from . import __version__, config, imap, server


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="postfach-mcp",
        description="Read-focused remote MCP server for IMAP mailboxes.",
    )
    parser.add_argument("--version", action="version", version=f"postfach-mcp {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    serve = commands.add_parser("serve", help="run the HTTP server")
    serve.add_argument("--host", help=f"bind address (overrides {config.PREFIX}HOST)")
    serve.add_argument("--port", type=int, help=f"port (overrides {config.PREFIX}PORT)")

    commands.add_parser("check", help="probe the IMAP login and list the folders")
    return parser


def _serve(args: argparse.Namespace) -> int:
    settings = config.load()
    app = server.build_app(settings)
    # uvicorn installs its own SIGINT/SIGTERM handlers and shuts down
    # gracefully, so a systemd stop needs no extra handling here.
    uvicorn.run(
        app,
        host=args.host or settings.host,
        port=args.port if args.port is not None else settings.port,
        log_level="info",
    )
    return 0


def _check() -> int:
    # No token needed: this command never opens the HTTP side.
    account = config.load(require_token=False).account
    with imap.open_mailbox(account) as box:
        folders = [f.name for f in box.folder.list()]

    print(f"login ok: {account.user} at {account.imap_host}:{account.imap_port}")
    for name in folders:
        marker = "  (drafts folder)" if name == account.drafts_folder else ""
        print(f"  {name}{marker}")

    if account.drafts_folder not in folders:
        print(
            f"drafts folder {account.drafts_folder!r} not found - "
            f"set {config.PREFIX}DRAFTS_FOLDER to one of the folders above",
            file=sys.stderr,
        )
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "serve":
            return _serve(args)
        return _check()
    except config.ConfigError as err:
        print(f"configuration error: {err}", file=sys.stderr)
        return 1
    except imap.ImapError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
