import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Protocol

from insurance_email_intake.errors import ReplyError
from insurance_email_intake.models import IntakeResult

_TEXTS = {
    "en": {
        "greeting": "Hello,",
        "pending": (
            "Thank you for your submission. To continue, we still need "
            "the following information:"
        ),
        "pending_end": "Please reply to this email with these details.",
        "unsupported": (
            "Thank you for your submission. It does not match a line of "
            "business we currently support, so we could not process it."
        ),
        "decided": "Your submission was received and assessed.",
        "decision": "Preliminary decision",
        "reference": "Reference",
        "disclaimer": (
            "This message was generated automatically and remains subject "
            "to underwriter review."
        ),
    },
    "fr": {
        "greeting": "Bonjour,",
        "pending": (
            "Merci pour votre soumission. Pour poursuivre, il nous manque "
            "encore les informations suivantes :"
        ),
        "pending_end": "Veuillez répondre à ce courriel avec ces précisions.",
        "unsupported": (
            "Merci pour votre soumission. Elle ne correspond pas à une "
            "ligne d'affaires que nous prenons en charge actuellement."
        ),
        "decided": "Votre soumission a été reçue et évaluée.",
        "decision": "Décision préliminaire",
        "reference": "Référence",
        "disclaimer": (
            "Ce message est généré automatiquement et demeure sujet à "
            "la révision d'un souscripteur."
        ),
    },
}


@dataclass(frozen=True)
class ReplyContext:
    recipient: str
    subject: str | None
    message_id: str | None


class ReplyPort(Protocol):
    def reply(self, context: ReplyContext, result: IntakeResult) -> None: ...


def render_reply_body(result: IntakeResult, language: str = "en") -> str:
    text = _TEXTS.get(language, _TEXTS["en"])
    lines = [text["greeting"], ""]
    if result.workflow_status == "PENDING_INFORMATION":
        lines.append(text["pending"])
        lines.extend(f"- {field}" for field in result.missing_fields)
        lines.extend(["", text["pending_end"]])
    elif result.workflow_status == "UNSUPPORTED_SUBMISSION":
        lines.append(text["unsupported"])
    else:
        lines.append(text["decided"])
        if result.decision:
            lines.append(f"{text['decision']}: {result.decision}")
        if result.decision_id:
            lines.append(f"{text['reference']}: {result.decision_id}")
    lines.extend(["", text["disclaimer"]])
    return "\n".join(lines)


def build_reply_message(
    sender_address: str,
    context: ReplyContext,
    result: IntakeResult,
    language: str = "en",
) -> EmailMessage:
    subject = (context.subject or "Your submission").strip()
    if not subject.lower().startswith(("re:", "réf:")):
        subject = f"Re: {subject}"

    message = EmailMessage()
    message["From"] = sender_address
    message["To"] = context.recipient
    message["Subject"] = subject
    message["Auto-Submitted"] = "auto-replied"
    if context.message_id:
        message["In-Reply-To"] = context.message_id
        message["References"] = context.message_id
    message.set_content(render_reply_body(result, language))
    return message


class SMTPResponder:
    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        language: str = "en",
        timeout_seconds: float = 20.0,
    ) -> None:
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.language = language
        self.timeout_seconds = timeout_seconds

    def reply(self, context: ReplyContext, result: IntakeResult) -> None:
        try:
            message = build_reply_message(self.user, context, result, self.language)
            with smtplib.SMTP_SSL(
                self.host, self.port, timeout=self.timeout_seconds
            ) as smtp:
                smtp.login(self.user, self.password)
                smtp.send_message(message)
        except (smtplib.SMTPException, OSError, ValueError) as error:
            raise ReplyError(str(error)) from error
