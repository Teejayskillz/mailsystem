from django.test import TestCase, override_settings
from django.utils import timezone

from generator.models import Address
from generator.services.addresses import ProvisioningError, ProvisioningService, generate_local_part

from .fakes import FakeCpanelClient

SETTINGS = dict(
    MAILGEN_ADDRESS_DOMAIN="example.com",
    MAILGEN_ADDRESS_PREFIX="otp-",
    MAILGEN_ADDRESS_LENGTH=10,
    MAILGEN_FORWARD_TO="primary@example.net",
    MAILGEN_MAX_ADDRESSES=5,
    MAILGEN_QUOTA_MB=100,
)


@override_settings(**SETTINGS)
class GenerationTests(TestCase):
    def test_local_part_is_unpredictable_and_prefixed(self):
        values = {generate_local_part() for _ in range(50)}
        self.assertEqual(len(values), 50)
        for value in values:
            self.assertTrue(value.startswith("otp-"))
            body = value[len("otp-"):]
            self.assertGreaterEqual(len(body), 10)
            self.assertNotIn("0", body)
            self.assertNotIn("o", body)
            self.assertNotIn("1", body)
            self.assertNotIn("l", body)


@override_settings(**SETTINGS)
class ProvisioningTests(TestCase):
    def setUp(self):
        self.cpanel = FakeCpanelClient()
        self.service = ProvisioningService(cpanel=self.cpanel)

    def test_create_provisions_mailbox_and_forwarder(self):
        address = self.service.create(label="test")

        self.assertEqual(address.status, Address.Status.ACTIVE)
        self.assertTrue(address.is_configured)
        self.assertTrue(self.cpanel.mailbox_exists(address.address))
        self.assertTrue(self.cpanel.forwarder_exists(address.address, "primary@example.net"))
        self.assertTrue(address.get_mailbox_password())
        self.assertNotIn(address.get_mailbox_password(), address.mailbox_password_enc)

    def test_create_fails_when_domain_is_not_a_mail_domain(self):
        service = ProvisioningService(cpanel=FakeCpanelClient(domains=("other.test",)))
        with self.assertRaisesMessage(ProvisioningError, "not a mail domain"):
            service.create()
        self.assertEqual(Address.objects.count(), 0)

    def test_create_rolls_back_mailbox_when_forwarder_fails(self):
        service = ProvisioningService(cpanel=FakeCpanelClient(fail={"add_forwarder"}))

        with self.assertRaises(ProvisioningError):
            service.create()

        address = Address.objects.get()
        self.assertEqual(address.status, Address.Status.FAILED)
        self.assertFalse(address.is_configured)
        self.assertEqual(address.last_error[:26], "Forwarder creation failed:")
        # The half-created mailbox must be removed again.
        self.assertFalse(service.cpanel.pops)
        self.assertTrue(service.cpanel.deleted_pops)

    def test_max_addresses_is_enforced(self):
        for index in range(5):
            Address.objects.create(
                address=f"existing{index}@example.com",
                local_part=f"existing{index}",
                domain="example.com",
                forward_to="primary@example.net",
                status=Address.Status.ACTIVE,
            )

        with self.assertRaisesMessage(ProvisioningError, "Address limit reached"):
            self.service.create()

    def test_disable_removes_forwarder_and_suspends_incoming(self):
        address = self.service.create()

        self.service.disable(address)
        address.refresh_from_db()

        self.assertEqual(address.status, Address.Status.DISABLED)
        self.assertFalse(address.is_configured)
        self.assertEqual(self.cpanel.forwarder_targets(address.address), [])
        self.assertTrue(self.cpanel.is_suspended_incoming(address.address))

    def test_enable_restores_forwarder_and_incoming(self):
        address = self.service.create()
        self.service.disable(address)
        self.service.enable(address)
        address.refresh_from_db()

        self.assertEqual(address.status, Address.Status.ACTIVE)
        self.assertTrue(address.is_configured)
        self.assertTrue(self.cpanel.forwarder_exists(address.address, "primary@example.net"))
        self.assertFalse(self.cpanel.is_suspended_incoming(address.address))

    def test_delete_removes_mailbox_and_clears_secret(self):
        address = self.service.create()
        self.service.delete(address)
        address.refresh_from_db()

        self.assertEqual(address.status, Address.Status.DELETED)
        self.assertFalse(self.cpanel.mailbox_exists(address.address))
        self.assertEqual(address.mailbox_password_enc, "")
        self.assertIsNotNone(address.deleted_at)

    def test_verify_marks_server_evidence(self):
        address = self.service.create()
        address.server_verified_at = None
        address.forwarder_verified_at = None
        address.save(update_fields=["server_verified_at", "forwarder_verified_at"])

        self.service.verify(address)
        address.refresh_from_db()

        self.assertIsNotNone(address.server_verified_at)
        self.assertIsNotNone(address.forwarder_verified_at)

    def test_delivery_evidence_is_independent_of_configuration(self):
        address = self.service.create()

        self.assertTrue(address.is_configured)
        self.assertFalse(address.is_inbox_capable)
        self.assertFalse(address.is_delivery_tested)

        address.imap_verified_at = timezone.now()
        address.first_external_mail_at = timezone.now()
        address.save()

        self.assertTrue(address.is_inbox_capable)
        self.assertTrue(address.is_delivery_tested)
