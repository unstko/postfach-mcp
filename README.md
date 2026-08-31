# postfach-mcp

A self-hosted remote [MCP](https://modelcontextprotocol.io) server that gives
an AI assistant read-focused access to any IMAP mailbox: search, read, create
drafts, light triage. *Postfach* is German for mailbox.

**Deliberately no send, no delete — by design, not by configuration.**
E-mail is untrusted third-party input; an assistant that reads it can be
manipulated by it. This server keeps the blast radius small: the worst a
hijacked session can do is file a draft or move a message — both sit in your
mailbox, in plain sight, reversible. A send tool may appear in a later
version, but only behind an explicit opt-in flag, unregistered by default.
Feature requests to weaken this stance will be declined.

## Status

Working toward v0.1. The code is complete and fully tested without network;
verification against a real IMAP server is still pending.

## Tools

| Tool | Purpose |
|---|---|
| `list_folders` | List all folders in the mailbox |
| `folder_status` | Message and unseen counts for a folder |
| `list_messages` | Newest messages in a folder |
| `search_messages` | Server-side IMAP search |
| `get_message` | Full message: headers, body, attachment metadata |
| `create_draft` | Build an RFC-822 message and file it in the drafts folder — never sends |
| `mark_read` | Set or clear the seen flag |
| `mark_flagged` | Set or clear the flagged star |
| `move_messages` | Move messages to another folder |

Messages are addressed by `folder` + `uid`; UIDs are per-folder. Reading
never sets the seen flag — only `mark_read` does, when asked.

## Installation

Requires Python 3.11+.

```bash
pip install git+https://github.com/unstko/postfach-mcp
```

Or from a clone: `pip install .` — both install the `postfach-mcp` command.

## Configuration

Everything is environment variables prefixed `POSTFACH_MCP_`; a commented
template is in [.env.example](.env.example). Missing or invalid variables
are reported together, each by name.

| Variable | Default | Purpose |
|---|---|---|
| `IMAP_HOST` | *(required)* | IMAP server to connect to |
| `IMAP_USER` | *(required)* | Login name |
| `IMAP_PASSWORD` | *(required)* | Password — use an app password if your provider offers them |
| `IMAP_PORT` | `993` | IMAP over TLS port |
| `DRAFTS_FOLDER` | `Drafts` | Folder that receives created drafts; `postfach-mcp check` verifies it exists |
| `FROM_ADDRESS` | `IMAP_USER` | From header for drafts, e.g. `Your Name <you@example.org>` |
| `FROM_ADDRESSES` | — | Comma-separated additional sender identities `create_draft` may select via its `from_address` argument; anything not listed here or in `FROM_ADDRESS` is rejected |
| `DRAFT_FORMAT` | `text` | `text` writes plain-text drafts; `html` adds an HTML rendering of the same text as a `multipart/alternative` part — for clients whose HTML-based composer collapses plain-text line breaks (Spark, for example) |
| `TOKEN` | *(required for `serve`)* | Bearer token, at least 32 characters (`openssl rand -hex 32`) |
| `HOST` | `127.0.0.1` | Bind address of the HTTP server |
| `PORT` | `8000` | Port of the HTTP server |
| `ALLOWED_HOSTS` | `127.0.0.1,localhost` | Comma-separated Host header allowlist — add the public name your proxy or tunnel uses |
| `ENABLE_SEND` | — | Reserved for a future explicit opt-in; not implemented in v0.1 |

## Running

```bash
postfach-mcp check   # probe the IMAP login, list folders, verify the drafts folder
postfach-mcp serve   # run the HTTP server (--host/--port override the environment)
```

`check` is the deploy diagnosis: it answers "are the credentials right, and
what is the drafts folder actually called on this server?" without starting
anything. `serve` exposes the MCP endpoint at `/mcp` and an unauthenticated
health probe at `/api/health`.

### Connecting a client

Register the server with Claude Code (any Streamable-HTTP MCP client works
the same way):

```bash
claude mcp add --transport http postfach https://mail.example.org/mcp \
  -H "Authorization: Bearer <token>" --scope user
```

## Security model

- **No send, no delete.** The server cannot transmit mail or destroy it;
  those tools do not exist at runtime. Drafts are filed via IMAP APPEND
  into your drafts folder and stay there until you act on them.
- **Mail content is untrusted.** Bodies and headers are returned in
  structured fields, never interpreted; tool descriptions warn the model
  that message content is third-party input. Header fields of drafts are
  validated against CRLF injection.
- **Bearer token** on every MCP request (constant-time comparison), minimum
  32 characters. The health endpoint is the only unauthenticated route.
- **Host header allowlist** (`ALLOWED_HOSTS`) rejects requests addressed
  under any other name — DNS-rebinding protection. Behind a proxy or
  tunnel you must add the public host name, or every request fails
  with 421.
- **Transport security is your job.** The server speaks plain HTTP and
  binds to localhost by default; put a TLS-terminating reverse proxy,
  tunnel, or VPN in front of it. Do not expose the port directly.
- **Errors are terse.** IMAP failures reach the client as one English
  sentence; credentials and tracebacks never do.

## Limitations

- One account per server instance.
- Drafts carry no formatting beyond line and paragraph breaks, and IMAP
  cannot edit them in place — a changed draft means a new one.
- Some clients render plain-text drafts through an HTML composer and lose
  all line breaks (observed in Spark on macOS and Android; webmail shows
  the same draft correctly). `DRAFT_FORMAT=html` works around this by
  adding an HTML alternative part.
- Attachments are reported as metadata only (name, type, size); their
  content is not retrievable.
- Message bodies are capped at 50,000 characters, list/search results at
  100 messages per call; drafts at 500,000 characters.
- HTML-only messages are converted to text with a deliberately simple
  converter — layout is lost, links are kept visible.
- `mark_read`, `mark_flagged` and `move_messages` trigger an expunge in
  the source folder (imap-tools behavior; a move is IMAP-internally
  copy + delete + expunge). Harmless for this server, which never sets
  the deleted flag itself, but it also purges messages other clients
  have marked deleted in that folder.

## Development

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest
.venv/bin/python -m ruff check . && .venv/bin/python -m mypy
```

Tests run entirely without network access — enforced by the test suite
itself, which fails any accidental socket connect.

## License

[MIT](LICENSE)

---

<sub>Built with assistance from <a href="https://claude.com/claude-code">Claude Code</a>.</sub>
