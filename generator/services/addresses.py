"""Address generation and cPanel provisioning.

Design rules:
  * the database is the collision gate (unique address + live count check)
  * every external step is verified by re-reading server state
  * failures never leave a half-configured address marked as working
"""

from __future__ import annotations

import logging
import secrets

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from ..models import Address
from .cpanel import CpanelClient, CpanelError

logger = logging.getLogger("mailgen")

# No look-alike characters (0/o, 1/l/i).
ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"


class ProvisioningError(Exception):
    """Administrator-facing error raised by provisioning actions."""


def generate_local_part(prefix: str | None = None, length: int | None = None) -> str:
    prefix = (prefix if prefix is not None else settings.MAILGEN_ADDRESS_PREFIX) or ""
    length = int(length if length is not None else settings.MAILGEN_ADDRESS_LENGTH)
    length = max(6, min(length, 40))
    prefix = "".join(ch for ch in prefix.lower() if ch.isalnum() or ch in "-_.")[:20]
    body = "".join(secrets.choice(ALPHABET) for _ in range(length))
    candidate = f"{prefix}{body}"
    # Must be a valid local part: start/end alphanumeric.
    if not candidate[0].isalnum():
        candidate = "x" + candidate
    if not candidate[-1].isalnum():
        candidate = candidate + "x"
    return candidate


class ProvisioningService:
    def __init__(self, cpanel: CpanelClient | None = None):
        self.cpanel = cpanel or CpanelClient.from_settings()

    # -- configuration ----------------------------------------------------
    @staticmethod
    def _domain() -> str:
        return (getattr(settings, "MAILGEN_ADDRESS_DOMAIN", "") or "").strip().lower()

    @staticmethod
    def _forward_to() -> str:
        return (getattr(settings, "MAILGEN_FORWARD_TO", "") or "").strip()

    def _assert_config(self) -> tuple[str, str]:
        domain = self._domain()
        forward_to = self._forward_to()
        if not domain:
            raise ProvisioningError("MAILGEN_ADDRESS_DOMAIN is not configured.")
        if not forward_to:
            raise ProvisioningError("MAILGEN_FORWARD_TO is not configured.")
        if not self.cpanel.is_configured:
            raise ProvisioningError(
                "cPanel API credentials are not configured; addresses cannot be provisioned."
            )
        return domain, forward_to

    # -- create -----------------------------------------------------------
    def create(self, label: str = "") -> Address:
        domain, forward_to = self._assert_config()

        max_addresses = int(getattr(settings, "MAILGEN_MAX_ADDRESSES", 10))
        if Address.objects.live().count() >= max_addresses:
            raise ProvisioningError(
                f"Address limit reached ({max_addresses}). Delete an address before creating more."
            )

        try:
            mail_domains = self.cpanel.list_mail_domains()
        except CpanelError as exc:
            raise ProvisioningError(str(exc)) from exc

        if domain not in mail_domains:
            raise ProvisioningError(
                f"{domain} is not a mail domain on this cPanel account. "
                "Check Email Routing / MX for the domain first."
            )

        local_part = self._pick_local_part(domain)
        address = f"{local_part}@{domain}"
        password = secrets.token_urlsafe(24)

        obj = Address(
            address=address,
            local_part=local_part,
            domain=domain,
            label=(label or "").strip()[:64],
            quota_mb=int(getattr(settings, "MAILGEN_QUOTA_MB", 100)),
            forward_to=forward_to,
            status=Address.Status.PENDING,
        )
        obj.set_mailbox_password(password)

        try:
            with transaction.atomic():
                obj.save()
        except IntegrityError as exc:
            raise ProvisioningError("Address collision while saving; please retry.") from exc

        # 1) mailbox
        try:
            self.cpanel.add_pop(address, password, obj.quota_mb)
        except CpanelError as exc:
            obj.mark_failed(f"Mailbox creation failed: {exc}")
            raise ProvisioningError(f"Mailbox creation failed: {exc}") from exc

        # 2) forwarder
        try:
            self.cpanel.add_forwarder(address, forward_to)
        except CpanelError as exc:
            self._safe_delete_pop(address)
            obj.mark_failed(f"Forwarder creation failed: {exc}")
            raise ProvisioningError(f"Forwarder creation failed: {exc}") from exc

        # 3) verify both objects actually exist
        try:
            self._verify(obj, expect_forwarder=True)
        except ProvisioningError:
            raise

        logger.info("address provisioned", extra={"address": address})
        return obj

    def _pick_local_part(self, domain: str) -> str:
        for _attempt in range(8):
            local_part = generate_local_part()
            candidate = f"{local_part}@{domain}"
            if Address.objects.filter(address=candidate).exists():
                continue
            if self.cpanel.mailbox_exists(candidate):
                continue
            return local_part
        raise ProvisioningError("Could not find an unused address; please retry.")

    # -- verification -----------------------------------------------------
    def _verify(self, obj: Address, expect_forwarder: bool) -> Address:
        pops = self.cpanel.list_pops()
        exists = any(str(p.get("email", "")).lower() == obj.address.lower() for p in pops)
        if not exists:
            obj.mark_failed("Mailbox is not visible in cPanel after the operation.")
            raise ProvisioningError("Mailbox is not visible in cPanel after the operation.")

        has_forwarder = self.cpanel.forwarder_exists(obj.address, obj.forward_to)
        if expect_forwarder and not has_forwarder:
            obj.mark_failed("Forwarder is not visible in cPanel after the operation.")
            raise ProvisioningError("Forwarder is not visible in cPanel after the operation.")

        now = timezone.now()
        obj.server_verified_at = now
        obj.forwarder_verified_at = now if has_forwarder else None
        obj.status = Address.Status.ACTIVE
        obj.last_error = ""
        obj.save(
            update_fields=[
                "server_verified_at",
                "forwarder_verified_at",
                "status",
                "last_error",
                "updated_at",
            ]
        )
        return obj

    def verify(self, obj: Address) -> Address:
        return self._verify(obj, expect_forwarder=obj.status == Address.Status.ACTIVE)

    # -- lifecycle --------------------------------------------------------
    def disable(self, obj: Address) -> Address:
        if obj.status == Address.Status.DELETED:
            raise ProvisioningError("This address has been deleted.")

        try:
            for destination in self.cpanel.forwarder_targets(obj.address):
                self.cpanel.delete_forwarder(obj.address, destination)
            self.cpanel.suspend_incoming(obj.address)

            remaining = self.cpanel.forwarder_targets(obj.address)
            if remaining:
                raise ProvisioningError(
                    "Forwarders still exist after removal: " + ", ".join(remaining)
                )
            if not self.cpanel.is_suspended_incoming(obj.address):
                raise ProvisioningError(
                    "cPanel did not confirm suspended incoming mail for this address."
                )
        except CpanelError as exc:
            obj.last_error = str(exc)[:500]
            obj.save(update_fields=["last_error", "updated_at"])
            raise ProvisioningError(str(exc)) from exc

        obj.status = Address.Status.DISABLED
        obj.forwarder_verified_at = None
        obj.last_error = ""
        obj.save(update_fields=["status", "forwarder_verified_at", "last_error", "updated_at"])
        logger.info("address disabled", extra={"address": obj.address})
        return obj

    def enable(self, obj: Address) -> Address:
        if obj.status == Address.Status.DELETED:
            raise ProvisioningError("This address has been deleted.")
        if not obj.forward_to:
            raise ProvisioningError("No forwarding destination is recorded for this address.")

        try:
            if not self.cpanel.forwarder_exists(obj.address, obj.forward_to):
                self.cpanel.add_forwarder(obj.address, obj.forward_to)
            self.cpanel.unsuspend_incoming(obj.address)
            self._verify(obj, expect_forwarder=True)
        except CpanelError as exc:
            obj.last_error = str(exc)[:500]
            obj.save(update_fields=["last_error", "updated_at"])
            raise ProvisioningError(str(exc)) from exc

        logger.info("address enabled", extra={"address": obj.address})
        return obj

    def delete(self, obj: Address) -> Address:
        try:
            for destination in self.cpanel.forwarder_targets(obj.address):
                self.cpanel.delete_forwarder(obj.address, destination)
            self.cpanel.delete_pop(obj.address)
        except CpanelError as exc:
            obj.last_error = str(exc)[:500]
            obj.save(update_fields=["last_error", "updated_at"])
            raise ProvisioningError(str(exc)) from exc

        obj.soft_delete()
        obj.mailbox_password_enc = ""
        obj.save(update_fields=["status", "deleted_at", "mailbox_password_enc", "updated_at"])
        logger.info("address deleted", extra={"address": obj.address})
        return obj

    # -- internals --------------------------------------------------------
    def _safe_delete_pop(self, email: str) -> None:
        try:
            self.cpanel.delete_pop(email)
        except CpanelError:
            logger.exception("cleanup of partially created mailbox failed", extra={"address": email})
