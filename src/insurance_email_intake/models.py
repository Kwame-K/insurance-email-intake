from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ParsedEmail(BaseModel):
    source_id: str
    message_id: str | None = None
    sender: str | None = None
    recipients: list[str] = Field(default_factory=list)
    subject: str | None = None
    sent_at: str | None = None
    language: str
    body: str
    content: str
    attachment_names: list[str] = Field(default_factory=list)


class IntakeStatus(StrEnum):
    PROCESSED = "PROCESSED"
    DUPLICATE = "DUPLICATE"
    UNAVAILABLE = "UNAVAILABLE"
    REJECTED = "REJECTED"


class IntakeRecord(BaseModel):
    email: ParsedEmail
    document_name: str | None = None
    overrides: dict[str, Any] = Field(default_factory=dict)
    workflow_status: str
    response: dict[str, Any]
    processed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class IntakeResult(BaseModel):
    status: IntakeStatus
    source_id: str | None = None
    workflow_status: str | None = None
    decision: str | None = None
    decision_id: str | None = None
    missing_fields: list[str] = Field(default_factory=list)
    attachments_not_processed: list[str] = Field(default_factory=list)
    message: str
