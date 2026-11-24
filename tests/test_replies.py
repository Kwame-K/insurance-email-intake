from insurance_email_intake.replies import referenced_message_ids, strip_quoted_text


def test_referenced_ids_are_deduplicated_most_recent_first() -> None:
    ids = referenced_message_ids("<b@x>", "<a@x> <b@x>")
    assert ids == ["<b@x>", "<a@x>"]


def test_quoted_history_is_removed() -> None:
    text = (
        "MFA is enabled. Limit 1M, retention 10k.\n\n"
        "On Mon, Nov 23, 2026 at 6:00 PM Demo <demo@gmail.com> wrote:\n"
        "> - mfa_enabled\n"
    )
    assert strip_quoted_text(text) == "MFA is enabled. Limit 1M, retention 10k."


def test_wrapped_attribution_line_is_removed() -> None:
    text = "Yes.\n\nOn Mon, 23 Nov 2026 at 18:00, Demo\n<demo@gmail.com> wrote:\n> old"
    assert strip_quoted_text(text) == "Yes."
