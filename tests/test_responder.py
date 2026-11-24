from insurance_email_intake.models import IntakeResult, IntakeStatus
from insurance_email_intake.responder import (
    ReplyContext,
    build_reply_message,
    render_reply_body,
)


def _result(**overrides: object) -> IntakeResult:
    data: dict[str, object] = {
        "status": IntakeStatus.PROCESSED,
        "message": "ok",
        "workflow_status": "PENDING_INFORMATION",
        "missing_fields": ["mfa_enabled", "requested_limit_cad"],
    }
    data.update(overrides)
    return IntakeResult(**data)  # type: ignore[arg-type]


def test_pending_reply_lists_missing_fields() -> None:
    body = render_reply_body(_result())
    assert "- mfa_enabled" in body
    assert "- requested_limit_cad" in body


def test_unsupported_reply_has_no_field_list() -> None:
    body = render_reply_body(
        _result(workflow_status="UNSUPPORTED_SUBMISSION", missing_fields=[])
    )
    assert "- " not in body


def test_reply_is_threaded_and_marked_automatic() -> None:
    context = ReplyContext("broker@example.com", "NorthLake cyber", "<abc@mail>")
    message = build_reply_message("demo@gmail.com", context, _result())
    assert message["Subject"] == "Re: NorthLake cyber"
    assert message["In-Reply-To"] == "<abc@mail>"
    assert message["Auto-Submitted"] == "auto-replied"
    assert message["To"] == "broker@example.com"
