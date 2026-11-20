import json
from pathlib import Path

import pytest

from insurance_email_intake.client import UnderwritingPort
from insurance_email_intake.errors import (
    NotCompletableError,
    RecordNotFoundError,
    UnderwritingUnavailableError,
)
from insurance_email_intake.intake import EmailIntakeService
from insurance_email_intake.models import IntakeStatus
from insurance_email_intake.store import RecordStore
from tests.helpers import (
    EVALUATED,
    EXTRACTION_DOWN,
    PENDING,
    FakeUnderwriting,
    make_eml,
)

SOURCE_ID = "EML-msg-001-broker.test"


def build(client: UnderwritingPort, tmp_path: Path) -> EmailIntakeService:
    return EmailIntakeService(client, RecordStore(tmp_path / "state"), persist=True)


def test_ingest_submits_a_broker_email_and_stores_the_result(tmp_path: Path) -> None:
    fake = FakeUnderwriting(EVALUATED)
    service = build(fake, tmp_path)

    result = service.ingest_bytes(make_eml(), document_name="a.eml")

    assert result.status is IntakeStatus.PROCESSED
    assert result.decision == "ACCEPT"
    assert result.decision_id == "DEC-1"
    payload = fake.calls[0]
    assert payload["source_type"] == "BROKER_EMAIL"
    assert payload["source_id"] == SOURCE_ID
    assert payload["persist"] is True
    assert payload["document_name"] == "a.eml"
    assert service.store.get(SOURCE_ID) is not None


def test_same_email_is_not_submitted_twice(tmp_path: Path) -> None:
    fake = FakeUnderwriting(EVALUATED)
    service = build(fake, tmp_path)

    service.ingest_bytes(make_eml())
    second = service.ingest_bytes(make_eml())

    assert second.status is IntakeStatus.DUPLICATE
    assert len(fake.calls) == 1


def test_unavailable_service_is_not_stored_and_is_retried(tmp_path: Path) -> None:
    fake = FakeUnderwriting(EVALUATED, error=UnderwritingUnavailableError("down"))
    service = build(fake, tmp_path)

    first = service.ingest_bytes(make_eml())
    fake.error = None
    second = service.ingest_bytes(make_eml())

    assert first.status is IntakeStatus.UNAVAILABLE
    assert second.status is IntakeStatus.PROCESSED
    assert len(fake.calls) == 2


def test_extraction_unavailable_is_not_stored(tmp_path: Path) -> None:
    service = build(FakeUnderwriting(EXTRACTION_DOWN), tmp_path)

    result = service.ingest_bytes(make_eml())

    assert result.status is IntakeStatus.UNAVAILABLE
    assert service.store.get(SOURCE_ID) is None


def test_empty_email_is_rejected(tmp_path: Path) -> None:
    fake = FakeUnderwriting(EVALUATED)

    result = build(fake, tmp_path).ingest_bytes(make_eml(body=""))

    assert result.status is IntakeStatus.REJECTED
    assert fake.calls == []


def test_complete_merges_overrides_and_resubmits(tmp_path: Path) -> None:
    fake = FakeUnderwriting(PENDING, EVALUATED)
    service = build(fake, tmp_path)
    first = service.ingest_bytes(make_eml())

    done = service.complete(SOURCE_ID, {"mfa_enabled": True})

    assert first.workflow_status == "PENDING_INFORMATION"
    assert first.missing_fields == ["mfa_enabled", "requested_limit_cad"]
    assert done.workflow_status == "EVALUATED"
    assert fake.calls[1]["overrides"] == {"mfa_enabled": True}
    assert fake.calls[1]["content"] == fake.calls[0]["content"]


def test_complete_rejects_unknown_and_already_evaluated_emails(tmp_path: Path) -> None:
    service = build(FakeUnderwriting(EVALUATED), tmp_path)

    with pytest.raises(RecordNotFoundError):
        service.complete("EML-unknown", {"mfa_enabled": True})

    service.ingest_bytes(make_eml())
    with pytest.raises(NotCompletableError):
        service.complete(SOURCE_ID, {"mfa_enabled": True})


def test_scan_inbox_reads_eml_files_and_sidecar_overrides(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "case.eml").write_bytes(make_eml())
    (inbox / "case.overrides.json").write_text(
        json.dumps({"requested_limit_cad": 3_000_000}), encoding="utf-8"
    )
    fake = FakeUnderwriting(EVALUATED)
    service = build(fake, tmp_path)

    results = service.scan_inbox(inbox)

    assert [r.status for r in results] == [IntakeStatus.PROCESSED]
    assert fake.calls[0]["overrides"] == {"requested_limit_cad": 3_000_000}
    assert fake.calls[0]["document_name"] == "case.eml"


def test_scan_inbox_rejects_invalid_sidecar(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "case.eml").write_bytes(make_eml())
    (inbox / "case.overrides.json").write_text("[1, 2]", encoding="utf-8")
    fake = FakeUnderwriting(EVALUATED)

    results = build(fake, tmp_path).scan_inbox(inbox)

    assert results[0].status is IntakeStatus.REJECTED
    assert fake.calls == []
