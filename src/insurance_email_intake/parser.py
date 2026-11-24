import hashlib
import re
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import getaddresses, make_msgid
from html.parser import HTMLParser

from insurance_email_intake.errors import EmptyEmailError
from insurance_email_intake.models import ParsedEmail

MAX_SOURCE_ID_LENGTH = 128
_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._:-]")
_WORD = re.compile(r"[a-zàâçéèêëîïôûùüÿœ']+")
_FRENCH_HINTS = frozenset(
    {
        "bonjour",
        "nous",
        "vous",
        "notre",
        "assurance",
        "demande",
        "soumission",
        "entreprise",
        "couverture",
        "chiffre",
        "affaires",
        "limite",
        "merci",
        "cordialement",
    }
)
_BLOCK_TAGS = frozenset({"br", "p", "div", "tr", "li"})
_SKIPPED_TAGS = frozenset({"script", "style"})


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIPPED_TAGS:
            self._skip_depth += 1
        if tag in _BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIPPED_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        if tag in _BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._chunks.append(data)

    def text(self) -> str:
        lines = [" ".join(line.split()) for line in "".join(self._chunks).splitlines()]
        return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def html_to_text(html: str) -> str:
    extractor = _TextExtractor()
    extractor.feed(html)
    extractor.close()
    return extractor.text()


def detect_language(text: str, default: str = "en") -> str:
    hits = sum(1 for word in _WORD.findall(text.lower()) if word in _FRENCH_HINTS)
    return "fr" if hits >= 3 else default


def build_source_id(message_id: str | None, raw: bytes) -> str:
    if message_id:
        cleaned = _UNSAFE_CHARS.sub("-", message_id.strip("<> ")).strip("-")
        candidate = f"EML-{cleaned}"
        if cleaned and len(candidate) <= MAX_SOURCE_ID_LENGTH:
            return candidate
        digest = hashlib.sha256(message_id.encode()).hexdigest()[:32]
        return f"EML-{digest}"
    return f"EML-{hashlib.sha256(raw).hexdigest()[:32]}"


def _header(message: EmailMessage, name: str) -> str | None:
    value = message[name]
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _extract_body(message: EmailMessage) -> str:
    part = message.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    content = str(part.get_content())
    if part.get_content_type() == "text/html":
        content = html_to_text(content)
    return content.strip()


def parse_eml(raw: bytes, default_language: str = "en") -> ParsedEmail:
    message = BytesParser(policy=policy.default).parsebytes(raw)

    body = _extract_body(message)
    if not body:
        raise EmptyEmailError("The email has no readable text body.")

    message_id = _header(message, "Message-ID")
    sender = _header(message, "From")
    subject = _header(message, "Subject")
    sent_at = _header(message, "Date")
    recipients = [
        address
        for _, address in getaddresses([str(v) for v in message.get_all("To", [])])
        if address
    ]

    headers = [
        ("From", sender),
        ("To", ", ".join(recipients) or None),
        ("Subject", subject),
        ("Date", sent_at),
    ]
    header_block = "\n".join(f"{name}: {value}" for name, value in headers if value)

    return ParsedEmail(
        source_id=build_source_id(message_id, raw),
        message_id=message_id,
        sender=sender,
        recipients=recipients,
        subject=subject,
        sent_at=sent_at,
        language=detect_language(f"{subject or ''} {body}", default_language),
        body=body,
        content=f"{header_block}\n\n{body}" if header_block else body,
        attachment_names=[
            part.get_filename() or "unnamed" for part in message.iter_attachments()
        ],
    )


def build_eml(
    sender: str,
    subject: str,
    body: str,
    message_id: str | None = None,
) -> bytes:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = "submissions@mga-demo.test"
    message["Subject"] = subject
    message["Message-ID"] = message_id or make_msgid(domain="intake.local")
    message.set_content(body)
    return message.as_bytes()
