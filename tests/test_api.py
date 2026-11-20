from pathlib import Path

from fastapi.testclient import TestClient

from insurance_email_intake.api import create_app
from insurance_email_intake.errors import UnderwritingUnavailableError
from insurance_email_intake.intake import EmailIntakeService
from insurance_email_intake.settings import Settings
from insurance_email_intake.store import RecordStore
from tests.helpers import EVALUATED, PENDING, FakeUnderwriting, make_eml

SOURCE_ID = "EML-msg-001-broker.test"


def build_client(fake: FakeUnderwriting, tmp_path: Path) -> TestClient:
    settings = Settings(
        inbox_dir=tmp_path / "inbox",
        state_dir=tmp_path / "state",
        watch_enabled=False,
    )
    service = EmailIntakeService(fake, RecordStore(settings.state_dir))
    return TestClient(create_app(service=service, settings=settings))


def test_health(tmp_path: Path) -> None:
    client = build_client(FakeUnderwriting(EVALUATED), tmp_path)

    assert client.get("/health").json() == {"status": "ok"}


def test_post_eml_returns_the_workflow_result(tmp_path: Path) -> None:
    client = build_client(FakeUnderwriting(EVALUATED), tmp_path)

    response = client.post(
        "/v1/emails/eml",
        content=make_eml(),
        headers={"Content-Type": "message/rfc822"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "PROCESSED"
    assert body["source_id"] == SOURCE_ID
    assert body["decision"] == "ACCEPT"


def test_post_eml_returns_502_when_underwriting_is_down(tmp_path: Path) -> None:
    fake = FakeUnderwriting(EVALUATED, error=UnderwritingUnavailableError("down"))
    client = build_client(fake, tmp_path)

    response = client.post("/v1/emails/eml", content=make_eml())

    assert response.status_code == 502
    assert response.json()["status"] == "UNAVAILABLE"


def test_post_text_builds_an_email(tmp_path: Path) -> None:
    fake = FakeUnderwriting(EVALUATED)
    client = build_client(fake, tmp_path)

    response = client.post(
        "/v1/emails/text",
        json={"subject": "Cyber quote", "body": "NorthLake needs cyber cover."},
    )

    assert response.status_code == 200
    assert "Subject: Cyber quote" in fake.calls[0]["content"]


def test_complete_flow_and_error_codes(tmp_path: Path) -> None:
    client = build_client(FakeUnderwriting(PENDING, EVALUATED), tmp_path)
    client.post("/v1/emails/eml", content=make_eml())

    done = client.post(
        f"/v1/emails/{SOURCE_ID}/complete",
        json={"overrides": {"mfa_enabled": True}},
    )
    again = client.post(
        f"/v1/emails/{SOURCE_ID}/complete",
        json={"overrides": {"mfa_enabled": True}},
    )
    missing = client.post(
        "/v1/emails/EML-unknown/complete",
        json={"overrides": {"mfa_enabled": True}},
    )
    invalid = client.post(
        "/v1/emails/bad id/complete",
        json={"overrides": {"mfa_enabled": True}},
    )

    assert done.status_code == 200
    assert done.json()["workflow_status"] == "EVALUATED"
    assert again.status_code == 409
    assert missing.status_code == 404
    assert invalid.status_code == 422


def test_list_and_get_processed_emails(tmp_path: Path) -> None:
    client = build_client(FakeUnderwriting(EVALUATED), tmp_path)
    client.post("/v1/emails/eml", content=make_eml())

    listing = client.get("/v1/emails")
    detail = client.get(f"/v1/emails/{SOURCE_ID}")
    unknown = client.get("/v1/emails/EML-unknown")

    assert [r["email"]["source_id"] for r in listing.json()] == [SOURCE_ID]
    assert detail.json()["workflow_status"] == "EVALUATED"
    assert unknown.status_code == 404
