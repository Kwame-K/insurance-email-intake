import imaplib
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager, suppress
from typing import Any, Protocol

from insurance_email_intake.errors import MailboxError


class MailboxSession(Protocol):
    def unseen_uids(self) -> list[str]: ...

    def fetch(self, uid: str) -> bytes: ...

    def mark_seen(self, uid: str) -> None: ...


class MailboxPort(Protocol):
    def open(self) -> AbstractContextManager[MailboxSession]: ...


class IMAPSession:
    def __init__(self, connection: imaplib.IMAP4_SSL) -> None:
        self.connection = connection

    def unseen_uids(self) -> list[str]:
        status, data = self.connection.uid("SEARCH", "UNSEEN")
        if status != "OK":
            raise MailboxError("IMAP SEARCH failed.")
        raw = data[0] if data and data[0] else b""
        return [uid.decode() for uid in raw.split()]

    def fetch(self, uid: str) -> bytes:
        status, data = self.connection.uid("FETCH", uid, "(BODY.PEEK[])")
        if status != "OK":
            raise MailboxError(f"IMAP FETCH failed for UID {uid}.")
        items: list[Any] = data
        for item in items:
            if isinstance(item, tuple) and isinstance(item[1], bytes):
                return item[1]
        raise MailboxError(f"Message UID {uid} not found.")

    def mark_seen(self, uid: str) -> None:
        status, _ = self.connection.uid("STORE", uid, "+FLAGS", "(\\Seen)")
        if status != "OK":
            raise MailboxError(f"IMAP STORE failed for UID {uid}.")


class IMAPMailbox:
    """Opens a short-lived IMAP connection per poll cycle."""

    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        folder: str = "INBOX",
        timeout_seconds: float = 30.0,
    ) -> None:
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.folder = folder
        self.timeout_seconds = timeout_seconds

    @contextmanager
    def open(self) -> Iterator[MailboxSession]:
        try:
            connection = imaplib.IMAP4_SSL(
                self.host, self.port, timeout=self.timeout_seconds
            )
            connection.login(self.user, self.password)
            status, _ = connection.select(self.folder)
            if status != "OK":
                raise MailboxError(f"Cannot select folder '{self.folder}'.")
        except (imaplib.IMAP4.error, OSError) as error:
            raise MailboxError(str(error)) from error

        try:
            yield IMAPSession(connection)
        except (imaplib.IMAP4.error, OSError) as error:
            raise MailboxError(str(error)) from error
        finally:
            with suppress(imaplib.IMAP4.error, OSError):
                connection.close()
            with suppress(imaplib.IMAP4.error, OSError):
                connection.logout()
