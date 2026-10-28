from django.test import TestCase, override_settings

from generator.models import Address, Message
from generator.services.sync import SyncService

from .fakes import FakeImapService, envelope

SETTINGS = dict(
    MAILGEN_ADDRESS_DOMAIN="example.com",
    MAILGEN_FORWARD_TO="primary@example.net",
    MAILGEN_MAX_ADDRESSES=10,
)


def make_address(**overrides) -> Address:
    data = dict(
        address="otp-abc123@example.com",
        local_part="otp-abc123",
        domain="example.com",
        forward_to="primary@example.net",
        status=Address.Status.ACTIVE,
        imap_verified_at=None,
    )
    data.update(overrides)
    address = Address(**data)
    address.set_mailbox_password("mailbox-secret")
    address.save()
    return address


@override_settings(**SETTINGS)
class SyncTests(TestCase):
    def test_imports_new_messages_and_sets_evidence(self):
        address = make_address()
        imap = FakeImapService(messages=[envelope(1), envelope(2)])
        service = SyncService(imap=imap)

        result = service.sync_address(address)
        address.refresh_from_db()

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["imported"], 2)
        self.assertEqual(Message.objects.filter(address=address).count(), 2)
        self.assertEqual(address.imap_last_uid, 2)
        self.assertEqual(address.imap_uidvalidity, 1)
        self.assertIsNotNone(address.imap_verified_at)
        self.assertIsNotNone(address.first_external_mail_at)
        self.assertIsNotNone(address.last_synced_at)

    def test_second_sync_does_not_duplicate(self):
        address = make_address()
        imap = FakeImapService(messages=[envelope(1), envelope(2)])
        service = SyncService(imap=imap)

        service.sync_address(address)
        second = service.sync_address(address)
        address.refresh_from_db()

        self.assertEqual(second["imported"], 0)
        self.assertEqual(Message.objects.filter(address=address).count(), 2)
        self.assertEqual(address.imap_last_uid, 2)

    def test_internal_sender_does_not_mark_delivery_tested(self):
        address = make_address()
        imap = FakeImapService(messages=[envelope(1, sender="someone@example.com")])
        service = SyncService(imap=imap)

        service.sync_address(address)
        address.refresh_from_db()

        self.assertIsNone(address.first_external_mail_at)

    def test_imap_failure_is_recorded_not_raised(self):
        address = make_address()
        service = SyncService(imap=FakeImapService(fail=True))

        result = service.sync_address(address)
        address.refresh_from_db()

        self.assertEqual(result["status"], "error")
        self.assertIn("simulated imap failure", address.last_error)

    def test_disabled_address_is_skipped(self):
        address = make_address(status=Address.Status.DISABLED)
        service = SyncService(imap=FakeImapService(messages=[envelope(1)]))

        result = service.sync_address(address)

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(Message.objects.count(), 0)

    def test_batch_respects_limit(self):
        make_address()
        make_address(address="otp-def456@example.com", local_part="otp-def456")

        results = SyncService(imap=FakeImapService(messages=[])).sync_batch(limit=1)

        self.assertEqual(len(results), 1)
