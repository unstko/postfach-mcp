# Changelog

All notable changes to this project are documented in this file. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions
follow [Semantic Versioning](https://semver.org/) — with the 0.x caveat that
the tool surface and configuration may still change between minor releases.

## [Unreleased]

## [0.2.0] - 2026-09-01

Bulk-friendly triage: feedback from the first large mailbox clean-up
(28,000 messages) turned into five additions. Still no send, no delete.

### Added

- `list_headers`: page through the header data of a whole folder, oldest
  first, up to 500 per call — uid, date, sender, subject, size and seen
  flag, plus any extra headers requested by name (`List-Unsubscribe`, for
  example). Offsets stay stable while paging.
- `create_folder`: create folders — creating only; deleting and renaming
  remain deliberately absent.
- `list_folders` accepts `with_counts` and reports message and unseen
  counts for every selectable folder in a single request.
- `search_messages` matches arbitrary headers server-side via
  `header_name`/`header_value`; an empty value means "the header exists",
  which is how `List-Unsubscribe` separates bulk mail from personal mail.
- `move_messages` returns a `uid_map` (source uid → uid in the target
  folder) whenever the server reports COPYUID (UIDPLUS) — the protocol
  that makes bulk moves reversible message by message.
- README: a "Connecting clients" section covering Claude Code and
  claude.ai custom connectors, including the request-header pitfalls.

## [0.1.0] - 2026-09-01

First release.

### Added

- Nine read-focused MCP tools over Streamable HTTP: `list_folders`,
  `folder_status`, `list_messages`, `search_messages`, `get_message`,
  `create_draft`, `mark_read`, `mark_flagged`, `move_messages` — deliberately
  no send and no delete.
- Bearer-token authentication with constant-time comparison; additional
  per-client tokens via `EXTRA_TOKENS` so one can be revoked without
  touching the others.
- Host header allowlist (`ALLOWED_HOSTS`) as DNS-rebinding protection.
- Draft creation via IMAP APPEND with CRLF-injection validation, an optional
  sender allowlist (`FROM_ADDRESSES`) and an optional HTML alternative part
  (`DRAFT_FORMAT=html`) for clients whose HTML-based composer collapses
  plain-text line breaks.
- `postfach-mcp check` as a deploy diagnosis: probes the IMAP login, lists
  folders, verifies the drafts folder — without starting a server.
- Unauthenticated health endpoint at `/api/health`.
- Test suite that runs entirely without network access, enforced by the
  suite itself.

[Unreleased]: https://github.com/unstko/postfach-mcp/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/unstko/postfach-mcp/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/unstko/postfach-mcp/releases/tag/v0.1.0
