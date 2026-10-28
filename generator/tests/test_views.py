from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from generator.models import Address, Message
from generator.services.addresses import ProvisioningService

User = get_user_model()

SETTINGS = dict(
    MAILGEN_ADDRESS_DOMAIN="example.com",
    MAILGEN_FORWARD_TO="primary@example.net",
    MAILGEN_MAX_ADDRESSES=10,
    MAILGEN_LOGIN_MAX_ATTEMPTS=5,
    MAILGEN_LOGIN_WINDOW_SECONDS=900,
)


def make_user(username="admin", staff=True, password="a-very-long-password-123"):
    user = User.objects.create_user(username=username, password=password)
    user.is_staff = staff
    user.is_superuser = staff
    user.save()
    return user


def make_address(**overrides) -> Address:
    data = dict(
        address="otp-view1@example.com",
        local_part="otp-view1",
        domain="example.com",
        forward_to="primary@example.net",
        status=Address.Status.ACTIVE,
        server_verified_at=timezone.now(),
        forwarder_verified_at=timezone.now(),
        imap_verified_at=timezone.now(),
    )
    data.update(overrides)
    address = Address(**data)
    address.set_mailbox_password("mailbox-secret")
    address.save()
    return address


@override_settings(**SETTINGS)
class AuthenticationTests(TestCase):
    def setUp(self):
        self.user = make_user()

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response["Location"])

    def test_login_success(self):
        response = self.client.post(
            reverse("login"), {"username": "admin", "password": "a-very-long-password-123"}
        )
        self.assertRedirects(response, "/")

    def test_non_staff_user_cannot_log_in(self):
        make_user(username="visitor", staff=False, password="another-long-password-123")
        response = self.client.post(
            reverse("login"), {"username": "visitor", "password": "another-long-password-123"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invalid credentials")
        self.assertFalse(response.wsgi_request.user.is_authenticated)

    def test_wrong_password_is_rejected(self):
        response = self.client.post(
            reverse("login"), {"username": "admin", "password": "wrong-password-123"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invalid credentials")

    def test_login_is_rate_limited(self):
        last_status = None
        for _ in range(7):
            response = self.client.post(
                reverse("login"), {"username": "admin", "password": "wrong-password-123"}
            )
            last_status = response.status_code
        self.assertEqual(last_status, 429)

    def test_logout_requires_post(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)

        response = self.client.post(reverse("logout"))
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("_auth_user_id", self.client.session)


@override_settings(**SETTINGS)
class CsrfTests(TestCase):
    def setUp(self):
        self.user = make_user()

    def test_post_without_csrf_token_is_rejected(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)

        response = client.post(reverse("generate_address"), {"label": "x"})

        self.assertEqual(response.status_code, 403)

    def test_post_with_csrf_token_is_allowed(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        # Prime the CSRF cookie, then reuse the token from the cookie.
        client.get(reverse("dashboard"))
        token = client.cookies["csrftoken"].value

        with patch.object(ProvisioningService, "create") as create:
            create.return_value = make_address()
            response = client.post(
                reverse("generate_address"), {"label": "x", "csrfmiddlewaretoken": token}
            )

        self.assertEqual(response.status_code, 302)


@override_settings(**SETTINGS)
class AddressViewTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)
        self.address = make_address()

    def test_dashboard_lists_address_and_evidence(self):
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.address.address)
        self.assertContains(response, "Configured")
        self.assertContains(response, "Inbox ✓")

    def test_address_detail_shows_messages(self):
        Message.objects.create(
            address=self.address,
            uidvalidity=1,
            uid=10,
            subject="Your verification code is 482913",
            from_addr="noreply@service.example",
            sent_at=timezone.now(),
        )
        response = self.client.get(reverse("address_detail", args=[self.address.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "482913")

    def test_address_detail_filter(self):
        Message.objects.create(
            address=self.address, uidvalidity=1, uid=11, subject="Invoice", from_addr="billing@x.test"
        )
        response = self.client.get(reverse("address_detail", args=[self.address.pk]), {"q": "invoice"})
        self.assertContains(response, "Invoice")

        response = self.client.get(reverse("address_detail", args=[self.address.pk]), {"q": "nomatch"})
        self.assertNotContains(response, "Invoice")

    @patch.object(ProvisioningService, "disable")
    def test_disable_action_calls_service(self, disable):
        response = self.client.post(
            reverse("address_action", args=[self.address.pk, "disable"])
        )
        self.assertEqual(response.status_code, 302)
        disable.assert_called_once()

    def test_unknown_action_is_ignored(self):
        response = self.client.post(
            reverse("address_action", args=[self.address.pk, "drop-database"])
        )
        self.assertEqual(response.status_code, 302)
        self.address.refresh_from_db()
        self.assertEqual(self.address.status, Address.Status.ACTIVE)

    def test_confirm_forward_sets_evidence(self):
        self.client.post(reverse("address_action", args=[self.address.pk, "confirm-forward"]))
        self.address.refresh_from_db()
        self.assertIsNotNone(self.address.forward_confirmed_at)


@override_settings(**SETTINGS)
class MessageViewTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)
        self.address = make_address()
        self.message = Message.objects.create(
            address=self.address,
            uidvalidity=1,
            uid=42,
            subject="Code 123456",
            from_addr="noreply@service.example",
            sent_at=timezone.now(),
        )

    def test_detail_marks_read(self):
        response = self.client.get(reverse("message_detail", args=[self.message.pk]))
        self.assertEqual(response.status_code, 200)
        self.message.refresh_from_db()
        self.assertTrue(self.message.is_read)

    @patch("generator.views.ImapService")
    def test_render_sanitises_and_sets_csp(self, imap_class):
        imap_class.return_value.fetch_message.return_value = {
            "html": '<p>Code 123456</p><script>alert(1)</script><img src="https://track.example/x.gif">',
            "text": "Code 123456",
        }

        response = self.client.get(reverse("message_render", args=[self.message.pk]))
        body = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn("123456", body)
        self.assertNotIn("<script", body.lower())
        self.assertNotIn("<img", body.lower())
        self.assertIn("sandbox", response["Content-Security-Policy"])
        self.assertEqual(response["X-Frame-Options"], "SAMEORIGIN")

    @patch("generator.views.ImapService")
    def test_render_handles_imap_failure(self, imap_class):
        from generator.services.imap import ImapError

        imap_class.return_value.fetch_message.side_effect = ImapError("mailbox offline")

        response = self.client.get(reverse("message_render", args=[self.message.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertIn("could not be loaded", response.content.decode())


@override_settings(**SETTINGS)
class DiagnosticsViewTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client.force_login(self.user)

    def test_offline_diagnostics_page(self):
        response = self.client.get(reverse("diagnostics"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Diagnostics")
        self.assertContains(response, "Django version")

    def test_diagnostics_never_leaks_the_api_token(self):
        response = self.client.get(reverse("diagnostics"))
        self.assertNotContains(response, "dummy-token")
