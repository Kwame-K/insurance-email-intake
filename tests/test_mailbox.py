from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from pydantic import ValidationError

from insurance_email_intake.errors import MailboxError, UnderwritingUnavailableError
from insurance_email_intake.intake import EmailIntakeService
from insurance_email_intake.models import IntakeStatus
from insurance_email_intake.poller import MailboxPoller
from insurance_email_intake.settings import Settings
from insurance_email_intake.store import RecordStore
from tests.helpers import EVALUATED, FakeUnderwriting, make_eml

ALLOWED = frozenset({"broker@broker.test"})


class FakeSession:
    def __init__(self, messages: dict[str, bytes]) -> None:
        self.messages = messages
        self.seen: set[str] = set()

    def unseen_uids(self) -> list[str]:
        return [uid for uid in self.messages if uid not in self.seen]

    def fetch(self, uid: str) -> bytes:
        return self.messages[uid]

    def mark_seen(self, uid: str) -> None:
        self.seen.add(uid)


class FakeMailbox:
    def __init__(
        self,
        messages: dict[str, bytes],
        error: Exception | None = None,
    ) -> None:
        self.session = FakeSession(messages)
        self.error = error

    @contextmanager
    def open(self) -> Iterator[FakeSession]:
        if self.error is not None:
            raise self.error
        yield self.session


def build(
    mailbox: FakeMailbox,
    fake: FakeUnderwriting,
    tmp_path: Path,
    max_bytes: int = 5_000_000,
) -> MailboxPoller:
    service = EmailIntakeService(fake, RecordStore(tmp_path / "state"))
    return MailboxPoller(mailbox, service, ALLOWED, max_bytes, 10)


def test_allowed_email_is_processed_and_marked_seen(tmp_path: Path) -> None:
    mailbox = FakeMailbox({"1": make_eml()})
    fake = FakeUnderwriting(EVALUATED)

    results = build(mailbox, fake, tmp_path).poll_once()

    assert [r.status for r in results] == [IntakeStatus.PROCESSED]
    assert mailbox.session.seen == {"1"}
    assert len(fake.calls) == 1


def test_unknown_sender_is_rejected_without_calling_underwriting(
    tmp_path: Path,
) -> None:
    mailbox = FakeMailbox({"1": make_eml(sender="Spam <spam@evil.test>")})
    fake = FakeUnderwriting(EVALUATED)

    results = build(mailbox, fake, tmp_path).poll_once()

    assert results[0].status is IntakeStatus.REJECTED
    assert "spam@evil.test" in results[0].message
    assert mailbox.session.seen == {"1"}
    assert fake.calls == []


def test_unavailable_underwriting_leaves_the_email_unseen(tmp_path: Path) -> None:
    mailbox = FakeMailbox({"1": make_eml()})
    fake = FakeUnderwriting(EVALUATED, error=UnderwritingUnavailableError("down"))
    poller = build(mailbox, fake, tmp_path)

    first = poller.poll_once()
    fake.error = None
    second = poller.poll_once()

    assert first[0].status is IntakeStatus.UNAVAILABLE
    assert second[0].status is IntakeStatus.PROCESSED
    assert mailbox.session.seen == {"1"}


def test_oversized_message_is_rejected(tmp_path: Path) -> None:
    mailbox = FakeMailbox({"1": make_eml()})
    fake = FakeUnderwriting(EVALUATED)

    results = build(mailbox, fake, tmp_path, max_bytes=10).poll_once()

    assert results[0].status is IntakeStatus.REJECTED
    assert fake.calls == []


def test_mailbox_error_is_reported_not_raised(tmp_path: Path) -> None:
    mailbox = FakeMailbox({}, error=MailboxError("login failed"))

    results = build(mailbox, FakeUnderwriting(EVALUATED), tmp_path).poll_once()

    assert results[0].status is IntakeStatus.UNAVAILABLE
    assert "login failed" in results[0].message


def test_imap_requires_credentials_and_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "IMAP_USER",
        "IMAP_PASSWORD",
        "IMAP_ALLOWED_SENDERS",
        "IMAP_HOST",
    ):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None, imap_enabled=True)  # type: ignore[call-arg]
