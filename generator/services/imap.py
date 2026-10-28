"""IMAP access through the maintained ``imap-tools`` library.

Only what the MVP needs: verify a login, fetch new message envelopes, and fetch
one full message for display. Message bodies are never persisted.
"""

from __future__ import annotations

import logging
import ssl
from datetime import datetime, timezone as dt_timezone

from django.conf import settings
from imap_tools import AND, MailBox, MailBoxStartTls

from ..models import Address

logger = logging.getLogger("mailgen")


class ImapError(Exception):
    """Administrator-safe IMAP failure."""


class ImapService:
    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        encryption: str | None = None,
        timeout: int | None = None,
        validate_cert: bool | None = None,
    ):
        self.host = (host if host is not None else getattr(settings, "IMAP_HOST", "")) or ""
        self.port = int(port if port is not None else getattr(settings, "IMAP_PORT", 993))
        self.encryption = (encryption or getattr(settings, "IMAP_ENCRYPTION", "ssl")).lower()
        self.timeout = int(timeout if timeout is not None else getattr(settings, "IMAP_TIMEOUT", 25))
        self.validate_cert = bool(
            validate_cert if validate_cert is not None else getattr(settings, "IMAP_VALIDATE_CERT", True)
        )

    # -- connection -------------------------------------------------------
    @property
    def is_configured(self) -> bool:
        return bool(self.host)

    def _ssl_context(self) -> ssl.SSLContext:
        if not self.validate_cert:
            return ssl._create_unverified_context()  # noqa: SLF001 - explicit opt-in only
        return ssl.create_default_context()

    def _mailbox(self, address: Address) -> MailBox:
        if not self.is_configured:
            raise ImapError("IMAP_HOST is not configured.")

        try:
            password = address.get_mailbox_password()
        except Exception as exc:  # DecryptionError or missing secret
            raise ImapError(f"Stored mailbox password unavailable: {exc}") from exc

        try:
            if self.encryption == "starttls":
                mailbox = MailBoxStartTls(self.host, self.port, self.timeout, ssl_context=self._ssl_context())
            else:
                mailbox = MailBox(self.host, self.port, self.timeout, ssl_context=self._ssl_context())
            mailbox.login(address.address, password, initial_folder="INBOX")
            return mailbox
        except Exception as exc:
            raise ImapError(f"IMAP login failed for {address.address}: {type(exc).__name__}") from exc

    # -- operations -------------------------------------------------------
    def verify(self, address: Address) -> None:
        """Prove IMAP access: login, open INBOX, read status, log out."""
        if address.status == Address.Status.DELETED:
            raise ImapError("Address is deleted.")
        with self._mailbox(address) as mailbox:
            status = mailbox.folder.status("INBOX")
            if "UIDVALIDITY" not in status:
                raise ImapError("IMAP server did not report UIDVALIDITY for INBOX.")

    def fetch_new(self, address: Address, limit: int | None = None) -> dict:
        """Fetch envelopes newer than ``address.imap_last_uid``.

        Returns ``{"uidvalidity": int, "reset": bool, "messages": [...]}``.
        """
        limit = int(limit or getattr(settings, "IMAP_MAX_MESSAGES", 100))
        since = int(address.imap_last_uid or 0)
        expected_uidvalidity = address.imap_uidvalidity

        with self._mailbox(address) as mailbox:
            status = mailbox.folder.status("INBOX")
            uidvalidity = int(status.get("UIDVALIDITY", 0))
            reset = bool(expected_uidvalidity and uidvalidity != int(expected_uidvalidity))

            if reset:
                logger.warning(
                    "UIDVALIDITY changed; resynchronising newest messages",
                    extra={"address": address.address},
                )
                since = 0

            rows: list[dict] = []
            if since > 0:
                criteria = AND(uid=f"{since + 1}:*")
                for msg in mailbox.fetch(criteria, mark_seen=False, limit=limit, reverse=False):
                    rows.append(self._envelope(msg))
            else:
                # First sync (or reset): take the newest page instead of the whole mailbox.
                newest = list(
                    mailbox.fetch(AND(all=True), mark_seen=False, limit=limit, reverse=True)
                )
                newest.reverse()
                rows.extend(self._envelope(msg) for msg in newest)

        return {"uidvalidity": uidvalidity, "reset": reset, "messages": rows}

    def fetch_message(self, address: Address, uid: int) -> dict:
        """Fetch one message body (not stored)."""
        with self._mailbox(address) as mailbox:
            for msg in mailbox.fetch(AND(uid=str(uid)), mark_seen=False, limit=1, bulk=True):
                return {
                    "uid": int(msg.uid),
                    "subject": msg.subject or "",
                    "from": msg.from_ or "",
                    "to": msg.to or "",
                    "date": _aware(msg.date),
                    "html": msg.html or "",
                    "text": msg.text or "",
                    "message_id": _header(msg, "message-id"),
                }
        raise ImapError(f"Message UID {uid} was not found in the mailbox.")

    # -- helpers ----------------------------------------------------------
    @staticmethod
    def _envelope(msg) -> dict:
        return {
            "uid": int(msg.uid or 0),
            "message_id": _header(msg, "message-id")[:255],
            "from_addr": (msg.from_ or "")[:254],
            "from_name": (msg.from_values.name if msg.from_values else "")[:190],
            "subject": (msg.subject or "")[:500],
            "sent_at": _aware(msg.date),
            "is_read": "\\Seen" in {str(flag) for flag in (msg.flags or ())},
        }


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=dt_timezone.utc)
    return value.astimezone(dt_timezone.utc)


def _header(msg, name: str) -> str:
    try:
        headers = msg.headers
        value = headers.get(name)
    except Exception:  # pragma: no cover - defensive
        return ""
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return str(value[0]) if value else ""
    return str(value)
