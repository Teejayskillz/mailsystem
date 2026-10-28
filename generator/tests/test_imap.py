"""IMAP adapter tests.

No live IMAP server is available in this environment, so the transport is
mocked at the library boundary. This verifies that the adapter issues the right
calls and maps the library's objects correctly; it does NOT prove connectivity
to a real Dovecot server (see docs/VERIFICATION.md).
"""
from datetime import datetime, timezone
from unittest.mock import patch

from django.test import TestCase, override_settings

from generator.models import Address
from generator.services.imap import ImapError, ImapService


class FakeAddress:
    def __init__(self, name="Sender", email="sender@example.net"):
        self.name = name
        self.email = email


class FakeMessage:
    def __init__(self, uid, subject="Your code is 123456", flags=()):
        self.uid = str(uid)
        self.subject = subject
        self.from_ = "Sender <sender@example.net>"
        self.from_values = FakeAddress()
        self.date = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
        self.flags = flags
        self.headers = {"message-id": (f"<{uid}@example.net>",)}
        self.html = "<p>Code: 123456</p><script>bad()</script>"
        self.text = "Code: 123456"
        self.to = "otp-test@example.com"


class FakeFolder:
    def __init__(self):
        self.status_calls = []

    def status(self, folder="INBOX"):
        self.status_calls.append(folder)
        return {"UIDVALIDITY": 7, "MESSAGES": 2, "UIDNEXT": 3, "UNSEEN": 1}


class FakeMailBox:
    instances = []

    def __init__(self, host="", port=993, timeout=None, ssl_context=None):
        self.host = host
        self.port = port
        self.ssl_context = ssl_context
        self.folder = FakeFolder()
        self.logged_in = None
        self.fetch_calls = []
        self.messages = [FakeMessage(1), FakeMessage(2, flags=("\\Seen",))]
        self.login_error = None
        FakeMailBox.instances.append(self)

    def login(self, username, password, initial_folder="INBOX"):
        if self.login_error:
            raise self.login_error
        self.logged_in = (username, password, initial_folder)
        return self

    def fetch(self, criteria, **kwargs):
        self.fetch_calls.append((str(criteria), kwargs))
        messages = list(self.messages)
        if kwargs.get("reverse"):
            messages.reverse()
        yield from messages

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def make_address(**overrides) -> Address:
    data = dict(
        address="otp-imap@example.com",
        local_part="otp-imap",
        domain="example.com",
        forward_to="primary@example.net",
        status=Address.Status.ACTIVE,
        imap_last_uid=0,
    )
    data.update(overrides)
    address = Address(**data)
    address.set_mailbox_password("mailbox-secret")
    address.save()
    return address


@override_settings(IMAP_HOST="imap.example.com", IMAP_PORT=993, IMAP_VALIDATE_CERT=True)
class ImapAdapterTests(TestCase):
    def setUp(self):
        FakeMailBox.instances.clear()

    @patch("generator.services.imap.MailBox", FakeMailBox)
    def test_login_uses_stored_credentials(self):
        address = make_address()
        ImapService(validate_cert=False).verify(address)

        mailbox = FakeMailBox.instances[-1]
        self.assertEqual(mailbox.host, "imap.example.com")
        self.assertEqual(mailbox.port, 993)
        self.assertEqual(mailbox.logged_in[0], address.address)
        self.assertEqual(mailbox.logged_in[1], "mailbox-secret")
        self.assertEqual(mailbox.folder.status_calls, ["INBOX"])

    @patch("generator.services.imap.MailBox", FakeMailBox)
    def test_first_sync_fetches_newest_page(self):
        address = make_address(imap_last_uid=0)
        result = ImapService().fetch_new(address, limit=50)

        self.assertEqual(result["uidvalidity"], 7)
        self.assertFalse(result["reset"])
        self.assertEqual(len(result["messages"]), 2)

        criteria, kwargs = FakeMailBox.instances[-1].fetch_calls[0]
        self.assertIn("ALL", criteria.upper())
        self.assertTrue(kwargs.get("reverse"))
        self.assertEqual(kwargs.get("limit"), 50)
        self.assertFalse(kwargs.get("mark_seen", True))

    @patch("generator.services.imap.MailBox", FakeMailBox)
    def test_incremental_fetch_uses_uid_range(self):
        address = make_address(imap_last_uid=5)
        ImapService().fetch_new(address, limit=10)

        criteria, _kwargs = FakeMailBox.instances[-1].fetch_calls[0]
        self.assertIn("UID 6:*", criteria)

    @patch("generator.services.imap.MailBox", FakeMailBox)
    def test_envelope_mapping(self):
        address = make_address()
        result = ImapService().fetch_new(address)

        first = result["messages"][0]
        self.assertEqual(first["uid"], 1)
        self.assertEqual(first["message_id"], "<1@example.net>")
        self.assertEqual(first["from_addr"], "Sender <sender@example.net>")
        self.assertEqual(first["from_name"], "Sender")
        self.assertFalse(first["is_read"])

        second = result["messages"][1]
        self.assertTrue(second["is_read"])

    @patch("generator.services.imap.MailBox", FakeMailBox)
    def test_uidvalidity_change_forces_resync(self):
        address = make_address(imap_last_uid=5, imap_uidvalidity=99)
        result = ImapService().fetch_new(address)

        self.assertTrue(result["reset"])
        criteria, _ = FakeMailBox.instances[-1].fetch_calls[0]
        self.assertIn("ALL", criteria.upper())

    @patch("generator.services.imap.MailBox", FakeMailBox)
    def test_fetch_message_returns_bodies(self):
        address = make_address()
        payload = ImapService().fetch_message(address, 1)

        self.assertIn("123456", payload["html"])
        self.assertEqual(payload["text"], "Code: 123456")
        self.assertEqual(payload["uid"], 1)

    @patch("generator.services.imap.MailBox", FakeMailBox)
    def test_unknown_uid_raises(self):
        address = make_address()
        FakeMailBox.instances.clear()

        class EmptyBox(FakeMailBox):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.messages = []

        with patch("generator.services.imap.MailBox", EmptyBox):
            with self.assertRaises(ImapError):
                ImapService().fetch_message(address, 99)

    def test_login_failure_is_safe(self):
        address = make_address()

        class FailingBox(FakeMailBox):
            def login(self, username, password, initial_folder="INBOX"):
                raise RuntimeError("authentication failed")

        with patch("generator.services.imap.MailBox", FailingBox):
            with self.assertRaises(ImapError) as ctx:
                ImapService().verify(address)

        message = str(ctx.exception)
        self.assertIn("IMAP login failed", message)
        self.assertNotIn("mailbox-secret", message)

    def test_missing_configuration_is_reported(self):
        address = make_address()
        with override_settings(IMAP_HOST=""):
            with self.assertRaisesMessage(ImapError, "IMAP_HOST is not configured"):
                ImapService().verify(address)
