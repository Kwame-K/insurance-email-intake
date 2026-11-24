import re

_MESSAGE_ID = re.compile(r"<[^<>\s]+>")
_QUOTE_INTRO = re.compile(
    r"^(on|le)\s.{0,300}?(wrote|a écrit)\s*:$",
    re.IGNORECASE,
)
_ORIGINAL_MARKER = re.compile(
    r"^-{2,}\s*(original message|message d'origine)\s*-{2,}$",
    re.IGNORECASE,
)
_MAX_REFERENCES = 20


def referenced_message_ids(in_reply_to: str, references: str) -> list[str]:
    """Message-IDs of a thread, direct parent first, then newest to oldest."""
    found: list[str] = list(dict.fromkeys(_MESSAGE_ID.findall(in_reply_to)))
    for message_id in reversed(_MESSAGE_ID.findall(references)):
        if message_id not in found:
            found.append(message_id)
    return found[:_MAX_REFERENCES]


def _is_quote_start(text: str) -> bool:
    return bool(_QUOTE_INTRO.match(text) or _ORIGINAL_MARKER.match(text))


def strip_quoted_text(text: str) -> str:
    """Keeps only the new text of a reply, dropping quoted history."""
    lines = text.splitlines()
    kept: list[str] = []
    for index, line in enumerate(lines):
        current = line.strip()
        following = lines[index + 1].strip() if index + 1 < len(lines) else ""
        if _is_quote_start(current) or _is_quote_start(f"{current} {following}"):
            break
        if current.startswith(">"):
            continue
        kept.append(line)
    return "\n".join(kept).strip()
