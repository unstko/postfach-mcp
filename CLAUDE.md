# postfach-mcp

Read-focused remote MCP server for IMAP mailboxes ("Postfach" is German for
mailbox). Exposes search, read, draft creation and light triage to MCP
clients over Streamable HTTP. Deliberately no send and no delete tools —
by design, not by configuration.

## Layout

```
src/postfach_mcp/
├── config.py    environment → frozen Settings; errors name every variable
├── imap.py      the ONLY module that touches the network (imap-tools MailBox)
├── message.py   pure conversion: MIME → dicts, HTML → text, draft building
├── tools.py     the MCP tool functions, registered as closures over Settings
├── auth.py      SDK-free ASGI bearer-token middleware
├── server.py    app assembly: health endpoint → auth → MCP streamable HTTP
└── cli.py       argparse entry point (`serve`, `check`)
```

## Rules that stand

- **Tests run without network.** A conftest fixture blocks socket connects;
  IMAP is faked at the `imap.MailBox` seam. Never add a test that talks to
  a real server.
- **`imap.py` is the only network seam.** New functionality talks to IMAP
  through it, so the fake in the tests keeps covering everything.
- **No send, no delete.** Do not add tools that transmit mail or destroy
  it. A send tool may only ever appear behind the reserved
  `POSTFACH_MCP_ENABLE_SEND` opt-in, unregistered by default.
- **Mail content is untrusted input.** It goes into structured return
  fields only; headers for drafts are validated against CRLF injection in
  `message.py` — keep both properties when changing these paths.
- **Nothing operator-specific in this repo.** Host names, ports and
  deployment details of any concrete installation stay outside.

## Working on it

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest
.venv/bin/python -m ruff check . && .venv/bin/python -m mypy
```
