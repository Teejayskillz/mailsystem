"""Regression tests for the production host/CSRF failures.

Covers:
  * normalisation of DJANGO_ALLOWED_HOSTS / DJANGO_CSRF_TRUSTED_ORIGINS
  * the hard-coded hosts/origins used by this deployment
  * Host headers that contain backslashes (www\\.mailsystem...)
  * CSRF origin handling for /login/ and /admin/login/
"""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings

from mailgen import config

User = get_user_model()

PRODUCTION_HOST = "mailsystem.nzdworld.com"
WWW_HOST = "www.mailsystem.nzdworld.com"
ESCAPED_HOST = r"www\.mailsystem\.nzdworld\.com"


class HostNormalisationTests(TestCase):
    def test_backslashes_are_removed(self):
        hosts = config.normalize_hosts(r"www\.mailsystem\.nzdworld\.com")
        self.assertEqual(hosts, [WWW_HOST])

    def test_quotes_whitespace_case_and_duplicates(self):
        hosts = config.normalize_hosts(
            ' "Mailsystem.nzdworld.com" ,  MAILS YSTEM.example , mailsystem.nzdworld.com ',
            strict=False,
        )
        self.assertIn("mailsystem.nzdworld.com", hosts)
        self.assertEqual(len([h for h in hosts if h == "mailsystem.nzdworld.com"]), 1)

    def test_ports_and_wildcards_are_allowed(self):
        hosts = config.normalize_hosts("example.com:8443,*.example.com")
        self.assertEqual(hosts, ["example.com:8443", "*.example.com"])

    def test_invalid_entry_raises_in_strict_mode(self):
        with self.assertRaisesMessage(config.ConfigError, "invalid host entry"):
            config.normalize_hosts("https://example.com")

    def test_invalid_entry_is_dropped_in_lenient_mode(self):
        hosts = config.normalize_hosts("https://example.com,good.example.com", strict=False)
        self.assertEqual(hosts, ["good.example.com"])

    def test_origins_normalised(self):
        origins = config.normalize_origins(
            r"https://mailsystem\.nzdworld\.com/, https://www.mailsystem.nzdworld.com"
        )
        self.assertEqual(
            origins,
            ["https://mailsystem.nzdworld.com", "https://www.mailsystem.nzdworld.com"],
        )

    def test_origin_with_path_is_rejected(self):
        with self.assertRaisesMessage(config.ConfigError, "invalid origin entry"):
            config.normalize_origins("https://example.com/login")

    def test_origin_without_scheme_is_rejected(self):
        with self.assertRaisesMessage(config.ConfigError, "invalid origin entry"):
            config.normalize_origins("mailsystem.nzdworld.com")


class HardcodedSettingsTests(TestCase):
    def test_allowed_hosts_are_clean_and_contain_both_names(self):
        hosts = settings.ALLOWED_HOSTS
        self.assertIn(PRODUCTION_HOST, hosts)
        self.assertIn(WWW_HOST, hosts)
        for host in hosts:
            self.assertNotIn("\\", host)
            self.assertNotIn("/", host)

    def test_csrf_trusted_origins_contain_both_https_origins(self):
        origins = settings.CSRF_TRUSTED_ORIGINS
        self.assertIn("https://" + PRODUCTION_HOST, origins)
        self.assertIn("https://" + WWW_HOST, origins)
        for origin in origins:
            self.assertTrue(origin.startswith(("http://", "https://")), origin)
            self.assertNotIn("\\", origin)

    def test_sanitizer_middleware_runs_first(self):
        self.assertEqual(
            settings.MIDDLEWARE[0], "generator.middleware.HostHeaderSanitizerMiddleware"
        )


class LoginWithEscapedHostTests(TestCase):
    def test_login_page_accepts_backslash_host(self):
        response = self.client.get("/login/", HTTP_HOST=ESCAPED_HOST)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Administrator sign in")

    def test_admin_login_accepts_backslash_host(self):
        response = self.client.get("/admin/login/", HTTP_HOST=ESCAPED_HOST)
        self.assertEqual(response.status_code, 200)

    def test_dashboard_still_rejects_foreign_host(self):
        response = self.client.get("/login/", HTTP_HOST="attacker.example")
        self.assertEqual(response.status_code, 400)


@override_settings(
    CSRF_TRUSTED_ORIGINS=[
        "https://mailsystem.nzdworld.com",
        "https://www.mailsystem.nzdworld.com",
    ]
)
class CsrfOriginTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="admin", password="a-very-long-password-123"
        )
        self.user.is_staff = True
        self.user.save()
        self.client = Client(enforce_csrf_checks=True)

    def _token(self, host=PRODUCTION_HOST):
        response = self.client.get("/login/", HTTP_HOST=host)
        self.assertEqual(response.status_code, 200)
        return self.client.cookies["csrftoken"].value

    def _post(self, host, origin, extra=None):
        data = {
            "username": "admin",
            "password": "a-very-long-password-123",
            "csrfmiddlewaretoken": self._token(host),
        }
        headers = {"HTTP_HOST": host, "HTTP_ORIGIN": origin}
        headers.update(extra or {})
        return self.client.post("/login/", data, **headers)

    def test_https_origin_is_accepted_even_without_forwarded_proto(self):
        """cPanel terminates TLS; the app may see http internally."""
        response = self._post(PRODUCTION_HOST, "https://" + PRODUCTION_HOST)
        self.assertEqual(response.status_code, 302)

    def test_www_https_origin_is_accepted(self):
        response = self._post(WWW_HOST, "https://" + WWW_HOST)
        self.assertEqual(response.status_code, 302)

    def test_forwarded_proto_https_is_accepted(self):
        response = self._post(
            PRODUCTION_HOST,
            "https://" + PRODUCTION_HOST,
            {"HTTP_X_FORWARDED_PROTO": "https"},
        )
        self.assertEqual(response.status_code, 302)

    def test_null_origin_is_rejected(self):
        response = self._post(PRODUCTION_HOST, "null")
        self.assertEqual(response.status_code, 403)

    def test_foreign_origin_is_rejected(self):
        response = self._post(PRODUCTION_HOST, "https://attacker.example")
        self.assertEqual(response.status_code, 403)

    def test_admin_login_accepts_trusted_origin(self):
        token = self.client.cookies.get("csrftoken")
        response = self.client.get("/admin/login/", HTTP_HOST=PRODUCTION_HOST)
        self.assertEqual(response.status_code, 200)
        token = self.client.cookies["csrftoken"].value
        response = self.client.post(
            "/admin/login/",
            {"username": "admin", "password": "", "csrfmiddlewaretoken": token},
            HTTP_HOST=PRODUCTION_HOST,
            HTTP_ORIGIN="https://" + PRODUCTION_HOST,
        )
        self.assertNotEqual(response.status_code, 403)

    def test_login_form_posts_to_its_own_url(self):
        response = self.client.get("/login/", HTTP_HOST=PRODUCTION_HOST)
        html = response.content.decode()

        self.assertIn('<form method="post"', html)
        self.assertNotIn('action="http', html)
        self.assertNotIn("<iframe", html.lower())
