from datetime import UTC, datetime
from email import message_from_bytes, policy

import pytest

from postfach_mcp import message
from tests.conftest import FakeMessage, fake_attachment


class TestHtmlToText:
    def test_tags_become_text_with_line_breaks(self):
        html = "<p>Hello</p><p>World</p>"
        assert message.html_to_text(html) == "Hello\n\nWorld"

    def test_script_and_style_are_dropped(self):
        html = "<style>p{color:red}</style><p>Visible</p><script>alert(1)</script>"
        assert message.html_to_text(html) == "Visible"

    def test_entities_are_decoded(self):
        assert message.html_to_text("Gr&uuml;&szlig;e &amp; mehr") == "Grüße & mehr"

    def test_link_target_stays_visible(self):
        html = '<a href="https://evil.example/x">harmless text</a>'
        assert message.html_to_text(html) == "harmless text (https://evil.example/x)"

    def test_link_equal_to_text_not_repeated(self):
        html = '<a href="https://a.example/">https://a.example/</a>'
        assert message.html_to_text(html) == "https://a.example/"


class TestHeaderSafety:
    def test_plain_value_passes(self):
        assert message.ensure_header_safe("Hello Grüße", "subject") == "Hello Grüße"

    @pytest.mark.parametrize("bad", ["a\r\nBcc: x@y.example", "a\nb", "a\x00b"])
    def test_control_characters_rejected(self, bad):
        with pytest.raises(ValueError, match="subject"):
            message.ensure_header_safe(bad, "subject")

    def test_parse_address_with_display_name(self):
        addr = message.parse_address("Bob Example <bob@example.org>", "to")
        assert addr.addr_spec == "bob@example.org"
        assert addr.display_name == "Bob Example"

    def test_parse_address_bare(self):
        assert message.parse_address("carol@example.org", "to").addr_spec == "carol@example.org"

    @pytest.mark.parametrize("bad", ["not-an-address", "", "a@b\r\nBcc: x@y.example"])
    def test_parse_address_rejects_garbage(self, bad):
        with pytest.raises(ValueError):
            message.parse_address(bad, "to")


class TestReading:
    def test_summarize(self):
        msg = FakeMessage(
            uid="7",
            subject="Grüße",
            from_="alice@example.org",
            date=datetime(2026, 8, 31, 10, 0, tzinfo=UTC),
            flags=("\\Seen",),
            size=321,
        )
        assert message.summarize(msg) == {
            "uid": "7",
            "date": "2026-08-31T10:00:00+00:00",
            "from": "alice@example.org",
            "subject": "Grüße",
            "seen": True,
            "size": 321,
        }

    def test_full_prefers_text(self):
        msg = FakeMessage(uid="1", text="plain text", html="<p>html</p>")
        result = message.full(msg, "INBOX")
        assert result["body"] == {"source": "text", "text": "plain text", "truncated": False}

    def test_full_falls_back_to_converted_html(self):
        msg = FakeMessage(uid="1", text="  ", html="<p>Nur &Uuml;ML</p>")
        body = message.full(msg, "INBOX")["body"]
        assert body["source"] == "html_converted"
        assert body["text"] == "Nur ÜML"

    def test_full_truncates_long_bodies(self):
        msg = FakeMessage(uid="1", text="x" * 100)
        body = message.full(msg, "INBOX", max_body_chars=10)["body"]
        assert body["truncated"] is True
        assert body["text"] == "x" * 10

    def test_full_attachments_metadata_only(self):
        att = fake_attachment("report.pdf", "application/pdf", 12345)
        result = message.full(FakeMessage(uid="1", attachments=(att,)), "INBOX")
        assert result["attachments"] == [
            {"filename": "report.pdf", "content_type": "application/pdf", "size": 12345}
        ]

    def test_full_threading_headers(self):
        msg = FakeMessage(
            uid="1",
            headers={
                "message-id": ("<abc@example.org>",),
                "in-reply-to": ("<parent@example.org>",),
                "references": ("<root@example.org> <parent@example.org>",),
            },
        )
        result = message.full(msg, "INBOX")
        assert result["message_id"] == "<abc@example.org>"
        assert result["in_reply_to"] == "<parent@example.org>"
        assert result["references"] == ["<root@example.org>", "<parent@example.org>"]


class TestBuildDraft:
    def test_roundtrip(self):
        draft = message.build_draft(
            from_address="Stefan <stefan@example.org>",
            to=["Bob <bob@example.org>", "carol@example.org"],
            cc=["dave@example.org"],
            subject="Grüße aus dem Test",
            body="Servus,\ndas ist ein Entwurf mit Umlauten: äöüß.",
            in_reply_to="<parent@example.org>",
            references=["<root@example.org>", "<parent@example.org>"],
        )
        parsed = message_from_bytes(draft.as_bytes(), policy=policy.default)
        assert parsed["From"] == "Stefan <stefan@example.org>"
        assert parsed["To"] == "Bob <bob@example.org>, carol@example.org"
        assert parsed["Cc"] == "dave@example.org"
        assert parsed["Subject"] == "Grüße aus dem Test"
        assert parsed["In-Reply-To"] == "<parent@example.org>"
        assert parsed["References"] == "<root@example.org> <parent@example.org>"
        # The sender's domain, never the local hostname of the machine.
        assert parsed["Message-ID"].endswith("@example.org>")
        assert parsed["Date"]
        assert "äöüß" in parsed.get_content()

    def test_rejects_header_injection_in_subject(self):
        with pytest.raises(ValueError, match="subject"):
            message.build_draft(
                from_address="s@example.org",
                to=["b@example.org"],
                subject="Hi\r\nBcc: hidden@example.org",
                body="x",
            )

    def test_rejects_injection_in_recipient(self):
        with pytest.raises(ValueError):
            message.build_draft(
                from_address="s@example.org",
                to=["b@example.org\r\nX-Evil: 1"],
                subject="Hi",
                body="x",
            )
