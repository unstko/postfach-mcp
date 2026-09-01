# Changelog

All notable changes to this project are documented in this file. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions
follow [Semantic Versioning](https://semver.org/) — with the 0.x caveat that
the tool surface and configuration may still change between minor releases.

## [Unreleased]

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

[Unreleased]: https://github.com/unstko/postfach-mcp/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/unstko/postfach-mcp/releases/tag/v0.1.0
