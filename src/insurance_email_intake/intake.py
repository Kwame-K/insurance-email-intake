import json
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from uuid import uuid4

from insurance_email_intake.client import UnderwritingPort
from insurance_email_intake.errors import (
    EmptyEmailError,
    NotCompletableError,
    RecordNotFoundError,
    UnderwritingUnavailableError,
)
from insurance_email_intake.models import (
    IntakeRecord,
    IntakeResult,
    IntakeStatus,
    ParsedEmail,
)
from insurance_email_intake.parser import parse_eml
from insurance_email_intake.replies import strip_quoted_text
from insurance_email_intake.store import RecordStore

PENDING_INFORMATION = "PENDING_INFORMATION"
EXTRACTION_UNAVAILABLE = "EXTRACTION_UNAVAILABLE"


def load_sidecar_overrides(eml_path: Path) -> dict[str, Any]:
    sidecar = eml_path.with_name(f"{eml_path.stem}.overrides.json")
    if not sidecar.exists():
        return {}
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Overrides file must contain a JSON object.")
    return data


def _optional_str(value: object) -> str | None:
    return None if value is None else str(value)


class EmailIntakeService:
    def __init__(
        self,
        client: UnderwritingPort,
        store: RecordStore,
        *,
        persist: bool = True,
        default_language: str = "en",
    ) -> None:
        self.client = client
        self.store = store
        self.persist = persist
        self.default_language = default_language
        self._lock = threading.Lock()

    def ingest_bytes(
        self,
        raw: bytes,
        overrides: Mapping[str, Any] | None = None,
        document_name: str | None = None,
    ) -> IntakeResult:
        try:
            email = parse_eml(raw, self.default_language)
        except EmptyEmailError as error:
            return IntakeResult(status=IntakeStatus.REJECTED, message=str(error))

        with self._lock:
            existing = self.store.get(email.source_id)
            if existing is not None:
                return self._to_result(
                    existing,
                    IntakeStatus.DUPLICATE,
                    "Email already processed; no new submission was made.",
                )
            return self._submit(email, dict(overrides or {}), document_name)

    def ingest_reply(
        self, raw: bytes, parent_source_ids: Sequence[str]
    ) -> IntakeResult | None:
        """Completes a pending submission from a threaded reply.

        Returns None when no stored submission matches the thread, so the
        caller can handle the email as a new submission.
        """
        try:
            reply = parse_eml(raw, self.default_language)
        except EmptyEmailError as error:
            return IntakeResult(status=IntakeStatus.REJECTED, message=str(error))

        with self._lock:
            record = None
            for source_id in parent_source_ids:
                record = self.store.get(source_id)
                if record is not None:
                    break
            if record is None:
                return None
            parent_id = record.email.source_id
            if record.workflow_status != PENDING_INFORMATION:
                return IntakeResult(
                    status=IntakeStatus.REJECTED,
                    source_id=parent_id,
                    workflow_status=record.workflow_status,
                    message="This submission is no longer awaiting information.",
                )
            new_text = strip_quoted_text(reply.body)
            if not new_text:
                return IntakeResult(
                    status=IntakeStatus.REJECTED,
                    source_id=parent_id,
                    workflow_status=record.workflow_status,
                    message="The reply contains no new text.",
                )
            merged = record.email.model_copy(
                update={
                    "body": f"{record.email.body}\n\n{new_text}",
                    "content": f"{record.email.content}\n\n{new_text}",
                }
            )
            return self._submit(merged, record.overrides, record.document_name)

    def complete(self, source_id: str, overrides: Mapping[str, Any]) -> IntakeResult:
        with self._lock:
            record = self.store.get(source_id)
            if record is None:
                raise RecordNotFoundError(f"Email '{source_id}' was not found.")
            if record.workflow_status != PENDING_INFORMATION:
                raise NotCompletableError(
                    f"Email '{source_id}' is {record.workflow_status}, "
                    "not pending information."
                )
            merged = {**record.overrides, **overrides}
            return self._submit(record.email, merged, record.document_name)

    def scan_inbox(self, inbox_dir: Path) -> list[IntakeResult]:
        if not inbox_dir.is_dir():
            return []

        results: list[IntakeResult] = []
        for path in sorted(inbox_dir.glob("*.eml")):
            try:
                overrides = load_sidecar_overrides(path)
                raw = path.read_bytes()
            except (OSError, ValueError) as error:
                results.append(
                    IntakeResult(
                        status=IntakeStatus.REJECTED,
                        message=f"{path.name}: {error}",
                    )
                )
                continue
            results.append(self.ingest_bytes(raw, overrides, document_name=path.name))
        return results

    def _submit(
        self,
        email: ParsedEmail,
        overrides: dict[str, Any],
        document_name: str | None,
    ) -> IntakeResult:
        payload = {
            "source_id": email.source_id,
            "source_type": "BROKER_EMAIL",
            "document_name": document_name,
            "content": email.content,
            "language": email.language,
            "overrides": overrides,
            "persist": self.persist,
        }

        try:
            response = self.client.extract_and_underwrite(
                payload,
                correlation_id=str(uuid4()),
            )
        except UnderwritingUnavailableError as error:
            return IntakeResult(
                status=IntakeStatus.UNAVAILABLE,
                source_id=email.source_id,
                attachments_not_processed=email.attachment_names,
                message=f"Underwriting service unavailable: {error}",
            )

        workflow_status = str(response.get("workflow_status", "UNKNOWN"))
        if workflow_status == EXTRACTION_UNAVAILABLE:
            return IntakeResult(
                status=IntakeStatus.UNAVAILABLE,
                source_id=email.source_id,
                workflow_status=workflow_status,
                attachments_not_processed=email.attachment_names,
                message=str(response.get("message", "Extraction unavailable.")),
            )

        record = IntakeRecord(
            email=email,
            document_name=document_name,
            overrides=overrides,
            workflow_status=workflow_status,
            response=response,
        )
        self.store.save(record)
        return self._to_result(
            record,
            IntakeStatus.PROCESSED,
            str(response.get("message", "")),
        )

    @staticmethod
    def _to_result(
        record: IntakeRecord,
        status: IntakeStatus,
        message: str,
    ) -> IntakeResult:
        raw_decision = record.response.get("decision")
        decision = raw_decision if isinstance(raw_decision, dict) else {}
        return IntakeResult(
            status=status,
            source_id=record.email.source_id,
            workflow_status=record.workflow_status,
            decision=_optional_str(decision.get("decision")),
            decision_id=_optional_str(decision.get("decision_id")),
            missing_fields=[
                str(f) for f in record.response.get("missing_fields") or []
            ],
            attachments_not_processed=record.email.attachment_names,
            message=message,
        )
