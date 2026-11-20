import pytest

from insurance_email_intake.errors import EmptyEmailError
from insurance_email_intake.parser import detect_language, parse_eml
from tests.helpers import make_eml


def test_parse_plain_email_builds_source_id_and_content() -> None:
    email = parse_eml(make_eml())

    assert email.source_id == "EML-msg-001-broker.test"
    assert email.sender == "Broker <broker@broker.test>"
    assert email.recipients == ["submissions@mga.test"]
    assert email.content.startswith("From: Broker <broker@broker.test>")
    assert "Subject: Cyber quote request" in email.content
    assert email.body in email.content
    assert email.language == "en"


def test_parse_html_only_email_strips_markup_and_scripts() -> None:
    html = (
        "<html><body><p>Revenue: CAD 4,200,000</p>"
        "<script>track()</script><p>Montreal</p></body></html>"
    )

    email = parse_eml(make_eml(html=html))

    assert "Revenue: CAD 4,200,000" in email.body
    assert "Montreal" in email.body
    assert "track()" not in email.body
    assert "<p>" not in email.body


def test_email_without_message_id_gets_a_stable_hash_id() -> None:
    raw = make_eml(message_id=None)

    first = parse_eml(raw)
    second = parse_eml(raw)

    assert first.source_id == second.source_id
    assert first.source_id.startswith("EML-")
    assert len(first.source_id) == 36


def test_very_long_message_id_stays_within_source_id_limit() -> None:
    email = parse_eml(make_eml(message_id=f"<{'a' * 200}@x.test>"))

    assert email.source_id.startswith("EML-")
    assert len(email.source_id) <= 128


def test_attachments_are_listed_but_not_processed() -> None:
    email = parse_eml(make_eml(attachments=("quote.pdf",)))

    assert email.attachment_names == ["quote.pdf"]


def test_empty_body_is_rejected() -> None:
    with pytest.raises(EmptyEmailError):
        parse_eml(make_eml(body=""))


def test_french_text_is_detected() -> None:
    text = "Bonjour, nous avons une demande de soumission. Merci, cordialement."

    assert detect_language(text) == "fr"
    assert detect_language("Please send a cyber quote.") == "en"
