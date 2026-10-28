import logging

from django.db import models
from django.utils import timezone

from .services.crypto import DecryptionError, get_cipher

logger = logging.getLogger("mailgen")


class AddressQuerySet(models.QuerySet):
    def live(self):
        return self.exclude(status=Address.Status.DELETED)

    def active(self):
        return self.filter(status=Address.Status.ACTIVE)


class Address(models.Model):
    """A generated address plus the evidence we have that it actually works.

    Three independent levels are tracked, in this order:
      * configured   -> mailbox + forwarder confirmed in cPanel
      * inbox-capable-> IMAP login + INBOX select succeeded
      * delivery-tested -> an external sender's message was actually fetched
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACTIVE = "active", "Active"
        DISABLED = "disabled", "Disabled"
        FAILED = "failed", "Failed"
        DELETED = "deleted", "Deleted"

    address = models.CharField(max_length=254, unique=True)
    local_part = models.CharField(max_length=64)
    domain = models.CharField(max_length=190)
    label = models.CharField(max_length=64, blank=True)

    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True
    )

    # Ciphertext only — never the plaintext mailbox password.
    mailbox_password_enc = models.TextField(blank=True)

    quota_mb = models.PositiveIntegerField(default=100)
    forward_to = models.CharField(max_length=254, blank=True)

    server_verified_at = models.DateTimeField(null=True, blank=True)
    forwarder_verified_at = models.DateTimeField(null=True, blank=True)
    imap_verified_at = models.DateTimeField(null=True, blank=True)
    first_external_mail_at = models.DateTimeField(null=True, blank=True)
    forward_confirmed_at = models.DateTimeField(null=True, blank=True)

    imap_uidvalidity = models.BigIntegerField(null=True, blank=True)
    imap_last_uid = models.BigIntegerField(default=0)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=500, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    objects = AddressQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"]),
        ]
        verbose_name_plural = "addresses"

    def __str__(self) -> str:
        return self.address

    # -- credentials ------------------------------------------------------
    def set_mailbox_password(self, raw: str) -> None:
        self.mailbox_password_enc = get_cipher().encrypt(raw)

    def get_mailbox_password(self) -> str:
        if not self.mailbox_password_enc:
            raise DecryptionError("No mailbox password is stored for this address.")
        return get_cipher().decrypt(self.mailbox_password_enc)

    # -- evidence levels --------------------------------------------------
    @property
    def is_configured(self) -> bool:
        return bool(
            self.status == self.Status.ACTIVE
            and self.server_verified_at
            and self.forwarder_verified_at
        )

    @property
    def is_inbox_capable(self) -> bool:
        return self.imap_verified_at is not None

    @property
    def is_delivery_tested(self) -> bool:
        return self.first_external_mail_at is not None

    @property
    def forward_confirmed(self) -> bool:
        return self.forward_confirmed_at is not None

    @property
    def is_actionable(self) -> bool:
        return self.status in {self.Status.ACTIVE, self.Status.DISABLED}

    @property
    def status_label(self) -> str:
        return self.get_status_display()

    @property
    def unread_count(self) -> int:
        return self.messages.filter(is_read=False).count()

    # -- state helpers ----------------------------------------------------
    def mark_failed(self, message: str) -> None:
        self.status = self.Status.FAILED
        self.last_error = (message or "")[:500]
        self.save(update_fields=["status", "last_error", "updated_at"])

    def clear_error(self) -> None:
        if self.last_error:
            self.last_error = ""
            self.save(update_fields=["last_error", "updated_at"])

    def soft_delete(self) -> None:
        self.status = self.Status.DELETED
        self.deleted_at = timezone.now()
        self.save(update_fields=["status", "deleted_at", "updated_at"])


class Message(models.Model):
    """Thin index of a message that lives in the mailbox. No body is stored."""

    address = models.ForeignKey(Address, on_delete=models.CASCADE, related_name="messages")
    uidvalidity = models.BigIntegerField()
    uid = models.BigIntegerField()
    message_id = models.CharField(max_length=255, blank=True)
    from_addr = models.CharField(max_length=254, blank=True)
    from_name = models.CharField(max_length=190, blank=True)
    subject = models.CharField(max_length=500, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-sent_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["address", "uidvalidity", "uid"], name="uq_message_address_uid"
            )
        ]
        indexes = [
            models.Index(fields=["address", "sent_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.subject or '(no subject)'} — {self.from_addr}"


class LoginAttempt(models.Model):
    ip = models.CharField(max_length=45)
    username = models.CharField(max_length=150)
    ok = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["ip", "created_at"]),
            models.Index(fields=["username", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.username} from {self.ip} ({'ok' if self.ok else 'failed'})"


class Throttle(models.Model):
    """Fixed-window counters used for login and action rate limiting."""

    bucket = models.CharField(max_length=32)
    key_hash = models.CharField(max_length=64)
    window_start = models.BigIntegerField()
    counter = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["bucket", "key_hash"], name="uq_throttle_bucket_key")
        ]

    def __str__(self) -> str:
        return f"{self.bucket}:{self.counter}"
