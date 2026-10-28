"""Incremental mailbox synchronisation.

No background worker: the dashboard triggers a small batch, and a management
command is available for cPanel cron.
"""

from __future__ import annotations

import logging
from datetime import datetime

from django.conf import settings
from django.db import IntegrityError
from django.utils import timezone

from ..models import Address, Message
from .imap import ImapError, ImapService

logger = logging.getLogger("mailgen")


class SyncService:
    def __init__(self, imap: ImapService | None = None):
        self.imap = imap or ImapService()

    def sync_address(self, address: Address) -> dict:
        if address.status != Address.Status.ACTIVE:
            return {"address": address.address, "status": "skipped", "reason": "not active"}

        try:
            result = self.imap.fetch_new(address)
        except ImapError as exc:
            self._record_error(address, str(exc))
            return {"address": address.address, "status": "error", "reason": str(exc)}
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("unexpected IMAP failure", extra={"address": address.address})
            self._record_error(address, f"Unexpected IMAP failure: {type(exc).__name__}")
            return {"address": address.address, "status": "error", "reason": type(exc).__name__}

        uidvalidity = int(result["uidvalidity"])
        messages = result["messages"]
        imported = 0
        highest_uid = int(address.imap_last_uid or 0)
        external_seen = False

        for row in messages:
            uid = int(row["uid"])
            if uid <= 0:
                continue
            highest_uid = max(highest_uid, uid)

            try:
                _, created = Message.objects.get_or_create(
                    address=address,
                    uidvalidity=uidvalidity,
                    uid=uid,
                    defaults={
                        "message_id": row["message_id"],
                        "from_addr": row["from_addr"],
                        "from_name": row["from_name"],
                        "subject": row["subject"],
                        "sent_at": row["sent_at"],
                        "is_read": row["is_read"],
                    },
                )
            except IntegrityError:
                created = False

            if created:
                imported += 1
                if self._is_external(row["from_addr"], address.domain):
                    external_seen = True
            else:
                if self._is_external(row["from_addr"], address.domain) and not address.first_external_mail_at:
                    external_seen = True

        address.imap_uidvalidity = uidvalidity
        address.imap_last_uid = highest_uid
        address.last_synced_at = timezone.now()
        address.last_error = ""
        address.imap_verified_at = address.imap_verified_at or timezone.now()
        if external_seen and not address.first_external_mail_at:
            address.first_external_mail_at = timezone.now()

        address.save(
            update_fields=[
                "imap_uidvalidity",
                "imap_last_uid",
                "last_synced_at",
                "last_error",
                "imap_verified_at",
                "first_external_mail_at",
                "updated_at",
            ]
        )

        return {
            "address": address.address,
            "status": "ok",
            "imported": imported,
            "uidvalidity": uidvalidity,
            "reset": bool(result.get("reset")),
        }

    def sync_batch(self, limit: int | None = None) -> list[dict]:
        limit = int(limit or getattr(settings, "IMAP_SYNC_BATCH", 5))
        # MySQL sorts NULL first in ASC order, which is what we want here.
        queryset = Address.objects.active().order_by("last_synced_at")[:limit]

        results: list[dict] = []
        for address in queryset:
            results.append(self.sync_address(address))
        return results

    @staticmethod
    def _is_external(from_addr: str, domain: str) -> bool:
        sender = (from_addr or "").strip().lower()
        if "@" not in sender:
            return False
        return not sender.endswith("@" + domain.lower())

    @staticmethod
    def _record_error(address: Address, message: str) -> None:
        address.last_error = message[:500]
        address.last_synced_at = timezone.now()
        address.save(update_fields=["last_error", "last_synced_at", "updated_at"])

    @staticmethod
    def mark_read(message: Message) -> None:
        if not message.is_read:
            message.is_read = True
            message.save(update_fields=["is_read"])
