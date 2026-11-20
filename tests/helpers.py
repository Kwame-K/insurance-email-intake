from collections.abc import Mapping, Sequence
from email.message import EmailMessage
from typing import Any

PENDING: dict[str, Any] = {
    "workflow_status": "PENDING_INFORMATION",
    "missing_fields": ["mfa_enabled", "requested_limit_cad"],
    "message": "Critical underwriting information is missing.",
}
EVALUATED: dict[str, Any] = {
    "workflow_status": "EVALUATED",
    "decision": {"decision": "ACCEPT", "decision_id": "DEC-1"},
    "persisted": True,
    "message": "Extraction mapped and evaluated; decision persisted.",
}
EXTRACTION_DOWN: dict[str, Any] = {
    "workflow_status": "EXTRACTION_UNAVAILABLE",
    "message": "Extractor is down.",
}


def make_eml(
    body: str = "NorthLake Analytics Inc. seeks cyber coverage. Revenue CAD 4,200,000.",
    subject: str = "Cyber quote request",
    message_id: str | None = "<msg-001@broker.test>",
    sender: str = "Broker <broker@broker.test>",
    html: str | None = None,
    attachments: Sequence[str] = (),
) -> bytes:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = "submissions@mga.test"
    message["Subject"] = subject
    message["Date"] = "Thu, 19 Nov 2026 09:00:00 -0500"
    if message_id:
        message["Message-ID"] = message_id
    if html is not None:
        message.set_content(html, subtype="html")
    else:
        message.set_content(body)
    for name in attachments:
        message.add_attachment(
            b"%PDF-1.4", maintype="application", subtype="pdf", filename=name
        )
    return message.as_bytes()


class FakeUnderwriting:
    def __init__(
        self,
        *responses: dict[str, Any],
        error: Exception | None = None,
    ) -> None:
        self.responses = list(responses)
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def extract_and_underwrite(
        self,
        payload: Mapping[str, Any],
        correlation_id: str,
    ) -> dict[str, Any]:
        self.calls.append(dict(payload))
        if self.error is not None:
            raise self.error
        if len(self.responses) > 1:
            return self.responses.pop(0)
        return self.responses[0]
