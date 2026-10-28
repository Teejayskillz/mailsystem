"""Regression tests for the Referrer-Policy / Origin: null interaction.

Per the Fetch standard, a ``no-referrer`` policy makes browsers serialize the
Origin of a same-origin form POST as the literal ``null``. Django's CSRF
middleware correctly rejects that, so every HTML page that hosts a form must
not send ``no-referrer``.
"""

from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from generator.models import Address, Message

User = get_user_model()

HOST = "mailsystem.nzdworld.com"


@override_settings(ALLOWED_HOSTS=["mailsystem.nzdworld.com", "testserver"])
class ReferrerPolicyTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="admin", password="a-very-long-password-123"
        )
        self.user.is_staff = True
        self.user.is_superuser = True
        self.user.save()

    def assertFormPagePolicy(self, response):
        policy = response.get("Referrer-Policy")
        self.assertIsNotNone(policy, "form pages must set an explicit Referrer-Policy")
        self.assertNotEqual(
            policy,
            "no-referrer",
            "no-referrer makes browsers send Origin: null on same-origin form POSTs",
        )
        self.assertEqual(policy, "same-origin")

    def test_setting_is_not_no_referrer(self):
        self.assertNotEqual(settings.SECURE_REFERRER_POLICY, "no-referrer")

    def test_login_page(self):
        response = self.client.get("/login/", HTTP_HOST=HOST)
        self.assertEqual(response.status_code, 200)
        self.assertFormPagePolicy(response)

    def test_admin_login_page(self):
        response = self.client.get("/admin/login/", HTTP_HOST=HOST)
        self.assertEqual(response.status_code, 200)
        self.assertFormPagePolicy(response)

    def test_dashboard_page(self):
        self.client.force_login(self.user)
        response = self.client.get("/", HTTP_HOST=HOST)
        self.assertEqual(response.status_code, 200)
        self.assertFormPagePolicy(response)

    def test_diagnostics_page(self):
        self.client.force_login(self.user)
        response = self.client.get("/diagnostics/", HTTP_HOST=HOST)
        self.assertEqual(response.status_code, 200)
        self.assertFormPagePolicy(response)

    def test_error_page(self):
        response = self.client.get("/does-not-exist/", HTTP_HOST=HOST)
        self.assertEqual(response.status_code, 404)
        self.assertFormPagePolicy(response)

    def test_csrf_failure_page(self):
        # POST without a token exercises the custom CSRF failure view.
        from django.test import Client

        client = Client(enforce_csrf_checks=True)
        response = client.post("/login/", {"username": "x"}, HTTP_HOST=HOST)
        self.assertEqual(response.status_code, 403)
        self.assertFormPagePolicy(response)

    def test_message_render_keeps_strict_no_referrer(self):
        """The sandboxed message document has no forms, so it keeps no-referrer."""
        address = Address.objects.create(
            address="otp-ref@example.com",
            local_part="otp-ref",
            domain="example.com",
            forward_to="primary@example.net",
            status=Address.Status.ACTIVE,
        )
        address.set_mailbox_password("mailbox-secret")
        address.save()

        message = Message.objects.create(
            address=address,
            uidvalidity=1,
            uid=1,
            subject="Test",
            from_addr="sender@example.net",
            sent_at=timezone.now(),
        )

        self.client.force_login(self.user)
        with patch("generator.views.ImapService") as imap:
            imap.return_value.fetch_message.return_value = {
                "html": "<p>Hello</p>",
                "text": "Hello",
            }
            response = self.client.get(
                f"/messages/{message.pk}/render/", HTTP_HOST=HOST
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Referrer-Policy"], "no-referrer")
        self.assertIn("sandbox", response["Content-Security-Policy"])

    def test_null_origin_still_rejected(self):
        """Changing the referrer policy must not make null trustworthy."""
        from django.test import Client

        client = Client(enforce_csrf_checks=True)
        response = client.get("/login/", HTTP_HOST=HOST)
        token = client.cookies["csrftoken"].value

        response = client.post(
            "/login/",
            {
                "username": "admin",
                "password": "a-very-long-password-123",
                "csrfmiddlewaretoken": token,
            },
            HTTP_HOST=HOST,
            HTTP_ORIGIN="null",
        )

        self.assertEqual(response.status_code, 403)
