import logging
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr

from insurance_email_intake.errors import MailboxError, ReplyError
from insurance_email_intake.intake import EmailIntakeService
from insurance_email_intake.mailbox import MailboxPort
from insurance_email_intake.models import IntakeResult, IntakeStatus
from insurance_email_intake.parser import build_source_id
from insurance_email_intake.replies import referenced_message_ids
from insurance_email_intake.responder import ReplyContext, ReplyPort

logger = logging.getLogger(__name__)

_MARK_AS_SEEN = frozenset(
    {IntakeStatus.PROCESSED, IntakeStatus.DUPLICATE, IntakeStatus.REJECTED}
)
_HEADER_NAMES = (
    "From",
    "Subject",
    "Message-ID",
    "Auto-Submitted",
    "Precedence",
    "In-Reply-To",
    "References",
)
_AUTOMATED_PRECEDENCE = frozenset({"bulk", "list", "junk"})


class MailboxPoller:
    """Reads unseen emails from allowed senders and hands them to the intake.

    Emails are marked as seen once handled; when the underwriting service is
    unavailable they stay unseen and are retried at the next cycle.
    Threaded replies complete the matching pending submission. A reply is
    sent only for newly processed emails from allowed senders.
    """

    def __init__(
        self,
        mailbox: MailboxPort,
        service: EmailIntakeService,
        allowed_senders: frozenset[str],
        max_message_bytes: int = 5_000_000,
        max_messages_per_cycle: int = 10,
        responder: ReplyPort | None = None,
    ) -> None:
        self.mailbox = mailbox
        self.service = service
        self.allowed_senders = allowed_senders
        self.max_message_bytes = max_message_bytes
        self.max_messages_per_cycle = max_messages_per_cycle
        self.responder = responder

    def poll_once(self) -> list[IntakeResult]:
        results: list[IntakeResult] = []
        try:
            with self.mailbox.open() as session:
                for uid in session.unseen_uids()[: self.max_messages_per_cycle]:
                    result = self._handle(session.fetch(uid))
                    results.append(result)
                    if result.status in _MARK_AS_SEEN:
                        session.mark_seen(uid)
        except MailboxError as error:
            results.append(
                IntakeResult(
                    status=IntakeStatus.UNAVAILABLE,
                    message=f"Mailbox error: {error}",
                )
            )
        return results

    def _handle(self, raw: bytes) -> IntakeResult:
        if len(raw) > self.max_message_bytes:
            return IntakeResult(
                status=IntakeStatus.REJECTED,
                message="Message exceeds the maximum accepted size.",
            )
        headers = self._headers(raw)
        sender = parseaddr(headers["From"])[1].lower()
        if sender not in self.allowed_senders:
            return IntakeResult(
                status=IntakeStatus.REJECTED,
                message=f"Sender not allowed: {sender or 'unknown'}.",
            )
        result = self._ingest(raw, headers)
        if (
            result.status is IntakeStatus.PROCESSED
            and self.responder is not None
            and self._is_replyable(headers)
        ):
            self._reply(headers, sender, result)
        return result

    def _ingest(self, raw: bytes, headers: dict[str, str]) -> IntakeResult:
        parent_ids = [
            build_source_id(message_id, raw)
            for message_id in referenced_message_ids(
                headers["In-Reply-To"], headers["References"]
            )
        ]
        if parent_ids:
            threaded = self.service.ingest_reply(raw, parent_ids)
            if threaded is not None:
                return threaded
        return self.service.ingest_bytes(raw)

    def _reply(
        self, headers: dict[str, str], sender: str, result: IntakeResult
    ) -> None:
        context = ReplyContext(
            recipient=sender,
            subject=headers["Subject"] or None,
            message_id=headers["Message-ID"] or None,
        )
        try:
            assert self.responder is not None
            self.responder.reply(context, result)
            logger.info("Reply sent to %s (%s)", sender, result.workflow_status)
        except ReplyError as error:
            logger.warning("Reply to %s failed: %s", sender, error)

    @staticmethod
    def _is_replyable(headers: dict[str, str]) -> bool:
        auto_submitted = headers["Auto-Submitted"].strip().lower()
        precedence = headers["Precedence"].strip().lower()
        return auto_submitted in ("", "no") and precedence not in _AUTOMATED_PRECEDENCE

    @staticmethod
    def _headers(raw: bytes) -> dict[str, str]:
        parsed = BytesParser(policy=policy.default).parsebytes(raw, headersonly=True)
        return {name: str(parsed.get(name, "") or "") for name in _HEADER_NAMES}
