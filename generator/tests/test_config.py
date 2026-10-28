"""Tests for DATABASE_URL / MAILGEN_URL parsing and startup validation."""

import os
from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles import finders
from django.test import SimpleTestCase

from mailgen import config

BASE = Path("/srv/app")


class DatabaseUrlTests(SimpleTestCase):
    def test_mysql_url(self):
        cfg = config.parse_database_url("mysql://user:secret@db.example.com/app", BASE)

        self.assertEqual(cfg["ENGINE"], "django.db.backends.mysql")
        self.assertEqual(cfg["NAME"], "app")
        self.assertEqual(cfg["USER"], "user")
        self.assertEqual(cfg["PASSWORD"], "secret")
        self.assertEqual(cfg["HOST"], "db.example.com")
        self.assertEqual(cfg["PORT"], "3306")
        self.assertEqual(cfg["OPTIONS"]["charset"], "utf8mb4")

    def test_percent_encoded_credentials_are_decoded(self):
        cfg = config.parse_database_url(
            "mysql://user:p%40ss%2Fword@127.0.0.1:3307/app?charset=utf8", BASE
        )

        self.assertEqual(cfg["PASSWORD"], "p@ss/word")
        self.assertEqual(cfg["PORT"], "3307")
        self.assertEqual(cfg["OPTIONS"]["charset"], "utf8")

    def test_mysql_pymysql_and_mariadb_schemes(self):
        for url in (
            "mysql+pymysql://u:p@h/db",
            "mariadb://u:p@h/db",
            "MYSQL://u:p@h/db",
        ):
            with self.subTest(url=url):
                cfg = config.parse_database_url(url, BASE)
                self.assertEqual(cfg["ENGINE"], "django.db.backends.mysql")

    def test_empty_password_is_allowed(self):
        cfg = config.parse_database_url("mysql://root@127.0.0.1:3307/mailgen", BASE)
        self.assertEqual(cfg["PASSWORD"], "")

    def test_unsupported_scheme(self):
        with self.assertRaisesMessage(config.ConfigError, "unsupported scheme"):
            config.parse_database_url("postgres://u:p@h/db", BASE)

    def test_missing_user(self):
        with self.assertRaisesMessage(config.ConfigError, "database user"):
            config.parse_database_url("mysql://db.example.com/app", BASE)

    def test_missing_database_name(self):
        with self.assertRaisesMessage(config.ConfigError, "database name"):
            config.parse_database_url("mysql://user:pass@db.example.com/", BASE)

    def test_invalid_port(self):
        with self.assertRaisesMessage(config.ConfigError, "invalid port"):
            config.parse_database_url("mysql://user:pass@host:notaport/db", BASE)

    def test_unknown_query_parameter_is_rejected(self):
        with self.assertRaisesMessage(config.ConfigError, "unsupported parameter"):
            config.parse_database_url("mysql://u:p@h/db?sslmode=require", BASE)

    def test_invalid_charset(self):
        with self.assertRaisesMessage(config.ConfigError, "charset"):
            config.parse_database_url("mysql://u:p@h/db?charset=latin1", BASE)

    def test_sqlite_relative_path(self):
        cfg = config.parse_database_url("sqlite:///db.sqlite3", BASE)
        self.assertEqual(cfg["NAME"], str(BASE / "db.sqlite3"))

    def test_sqlite_absolute_path(self):
        cfg = config.parse_database_url("sqlite:////var/data/app.db", BASE)
        self.assertTrue(Path(cfg["NAME"]).is_absolute())
        self.assertTrue(cfg["NAME"].endswith("app.db"))

    def test_sqlite_memory(self):
        cfg = config.parse_database_url("sqlite://:memory:", BASE)
        self.assertEqual(cfg["NAME"], ":memory:")

    def test_empty_url(self):
        with self.assertRaisesMessage(config.ConfigError, "empty"):
            config.parse_database_url("   ", BASE)


class MailgenUrlTests(SimpleTestCase):
    def test_full_url(self):
        cfg = config.parse_mailgen_url(
            "mailgen://example.com?prefix=otp-&length=12&forward_to=Me@Example.NET"
            "&max_addresses=7&quota_mb=250"
        )

        self.assertEqual(cfg["domain"], "example.com")
        self.assertEqual(cfg["prefix"], "otp-")
        self.assertEqual(cfg["length"], 12)
        self.assertEqual(cfg["forward_to"], "me@example.net")
        self.assertEqual(cfg["max_addresses"], 7)
        self.assertEqual(cfg["quota_mb"], 250)

    def test_defaults(self):
        cfg = config.parse_mailgen_url("mailgen://example.com")

        self.assertEqual(cfg["prefix"], "otp-")
        self.assertEqual(cfg["length"], 10)
        self.assertEqual(cfg["max_addresses"], 10)
        self.assertEqual(cfg["quota_mb"], 100)
        self.assertEqual(cfg["forward_to"], "")

    def test_domain_from_query_parameter(self):
        cfg = config.parse_mailgen_url("mailgen://?domain=example.org&prefix=x-")
        self.assertEqual(cfg["domain"], "example.org")

    def test_same_domain_in_host_and_query_is_allowed(self):
        cfg = config.parse_mailgen_url("mailgen://example.com?domain=example.com")
        self.assertEqual(cfg["domain"], "example.com")

    def test_conflicting_domain_values(self):
        with self.assertRaisesMessage(config.ConfigError, "given twice"):
            config.parse_mailgen_url("mailgen://example.com?domain=other.com")

    def test_wrong_scheme(self):
        with self.assertRaisesMessage(config.ConfigError, "mailgen://"):
            config.parse_mailgen_url("https://example.com")

    def test_credentials_are_rejected(self):
        with self.assertRaisesMessage(config.ConfigError, "credentials"):
            config.parse_mailgen_url("mailgen://user:pass@example.com")

    def test_path_is_rejected(self):
        with self.assertRaisesMessage(config.ConfigError, "path"):
            config.parse_mailgen_url("mailgen://example.com/addresses")

    def test_fragment_is_rejected(self):
        with self.assertRaisesMessage(config.ConfigError, "fragment"):
            config.parse_mailgen_url("mailgen://example.com#x")

    def test_unknown_parameter_is_rejected(self):
        with self.assertRaisesMessage(config.ConfigError, "forwad_to"):
            config.parse_mailgen_url("mailgen://example.com?forwad_to=a@b.co")

    def test_duplicate_parameter_is_rejected(self):
        with self.assertRaisesMessage(config.ConfigError, "repeats"):
            config.parse_mailgen_url("mailgen://example.com?length=10&length=12")

    def test_non_integer_length(self):
        with self.assertRaisesMessage(config.ConfigError, "length must be an integer"):
            config.parse_mailgen_url("mailgen://example.com?length=ten")

    def test_empty_url(self):
        with self.assertRaisesMessage(config.ConfigError, "empty"):
            config.parse_mailgen_url("")


class ResolveMailSettingsTests(SimpleTestCase):
    def test_url_only(self):
        cfg = config.resolve_mail_settings(
            {"MAILGEN_URL": "mailgen://example.com?forward_to=a@b.co&max_addresses=3"}
        )
        self.assertEqual(cfg["domain"], "example.com")
        self.assertEqual(cfg["max_addresses"], 3)

    def test_individual_variables_override_url(self):
        cfg = config.resolve_mail_settings(
            {
                "MAILGEN_URL": "mailgen://example.com?prefix=url-&length=8",
                "MAILGEN_ADDRESS_PREFIX": "env-",
                "MAILGEN_ADDRESS_LENGTH": "14",
                "MAILGEN_MAX_ADDRESSES": "4",
            }
        )
        self.assertEqual(cfg["prefix"], "env-")
        self.assertEqual(cfg["length"], 14)
        self.assertEqual(cfg["max_addresses"], 4)

    def test_no_url_uses_defaults(self):
        cfg = config.resolve_mail_settings({})
        self.assertEqual(cfg["domain"], "")
        self.assertEqual(cfg["prefix"], "otp-")

    def test_invalid_override_integer(self):
        with self.assertRaisesMessage(config.ConfigError, "MAILGEN_MAX_ADDRESSES"):
            config.resolve_mail_settings({"MAILGEN_MAX_ADDRESSES": "lots"})


class MailValidationTests(SimpleTestCase):
    def valid(self, **overrides):
        cfg = dict(config.MAILGEN_DEFAULTS)
        cfg.update(
            {"domain": "example.com", "forward_to": "primary@example.net", **overrides}
        )
        return cfg

    def test_valid_configuration(self):
        self.assertEqual(config.validate_mail_settings(self.valid()), [])

    def test_missing_domain_is_only_an_error_when_required(self):
        cfg = self.valid(domain="")
        self.assertTrue(config.validate_mail_settings(cfg, require_configured=True))
        self.assertEqual(config.validate_mail_settings(cfg, require_configured=False), [])

    def test_invalid_domain(self):
        errors = config.validate_mail_settings(self.valid(domain="not a domain"))
        self.assertTrue(any("valid domain" in error for error in errors))

    def test_invalid_prefix(self):
        errors = config.validate_mail_settings(self.valid(prefix="bad prefix!"))
        self.assertTrue(any("prefix" in error for error in errors))

    def test_length_bounds(self):
        for length in (5, 41):
            with self.subTest(length=length):
                errors = config.validate_mail_settings(self.valid(length=length))
                self.assertTrue(any("length" in error for error in errors))

    def test_invalid_forwarding_address(self):
        errors = config.validate_mail_settings(self.valid(forward_to="nope"))
        self.assertTrue(any("forwarding" in error.lower() for error in errors))

    def test_max_addresses_bounds(self):
        errors = config.validate_mail_settings(self.valid(max_addresses=0))
        self.assertTrue(any("Maximum addresses" in error for error in errors))

    def test_quota_bounds(self):
        errors = config.validate_mail_settings(self.valid(quota_mb=0))
        self.assertTrue(any("quota" in error.lower() for error in errors))


class CoreValidationTests(SimpleTestCase):
    def call(self, **overrides):
        values = dict(
            debug=False,
            secret_key="x" * 60,
            allowed_hosts=["app.example.com"],
            field_key="A" * 43 + "=",
            cpanel_base_url="https://server.example.com:2083",
            imap_host="mail.example.com",
        )
        values.update(overrides)
        return config.validate_core(**values)

    def test_valid(self):
        self.assertEqual(self.call(), [])

    def test_missing_secret_key(self):
        self.assertTrue(any("DJANGO_SECRET_KEY" in error for error in self.call(secret_key="")))

    def test_short_secret_key_in_production(self):
        self.assertTrue(any("too short" in error for error in self.call(secret_key="short")))

    def test_short_secret_key_allowed_in_debug(self):
        self.assertEqual(self.call(debug=True, secret_key="short"), [])

    def test_empty_allowed_hosts(self):
        self.assertTrue(any("ALLOWED_HOSTS" in error for error in self.call(allowed_hosts=[])))

    def test_wildcard_hosts_rejected_in_production(self):
        self.assertTrue(
            any("must not contain" in error for error in self.call(allowed_hosts=["*"]))
        )

    def test_invalid_field_key(self):
        self.assertTrue(any("MAILGEN_FIELD_KEY" in error for error in self.call(field_key="not-a-key")))

    def test_missing_field_key_is_not_a_core_error(self):
        # Missing is reported by the system check so bootstrap commands still run.
        self.assertEqual(self.call(field_key=""), [])

    def test_cpanel_url_validation(self):
        for url in ("ftp://host", "https://user:pass@host", "http://host"):
            with self.subTest(url=url):
                self.assertTrue(
                    any("CPANEL_BASE_URL" in error for error in self.call(cpanel_base_url=url))
                )

    def test_imap_host_validation(self):
        self.assertTrue(
            any("IMAP_HOST" in error for error in self.call(imap_host="imaps://mail.example.com"))
        )

    def test_error_messages_never_echo_secrets(self):
        secret = "sup3r-secret-password"
        messages = " ".join(
            self.call(
                secret_key="",
                field_key="bad-" + secret,
                cpanel_base_url=f"https://user:{secret}@host",
            )
        )
        self.assertNotIn(secret, messages)


class StartupSettingsTests(SimpleTestCase):
    def test_urls_are_applied_to_settings(self):
        self.assertEqual(settings.MAILGEN_ADDRESS_DOMAIN, "example.com")
        self.assertEqual(settings.MAILGEN_FORWARD_TO, "primary@example.com")
        self.assertEqual(settings.MAILGEN_MAX_ADDRESSES, 10)
        self.assertEqual(settings.DATABASES["default"]["ENGINE"], "django.db.backends.mysql")

    def test_secure_defaults(self):
        # SESSION_COOKIE_SECURE is derived from DEBUG at startup, so only the
        # unconditional hardening is asserted here.
        self.assertEqual(settings.SESSION_COOKIE_SAMESITE, "Strict")
        self.assertTrue(settings.SESSION_COOKIE_HTTPONLY)
        self.assertTrue(settings.X_FRAME_OPTIONS == "DENY")
        self.assertEqual(settings.CSRF_COOKIE_SAMESITE, "Strict")

    def test_production_mode_requires_secure_cookies(self):
        """DEBUG=0 must turn on Secure cookies and HTTPS redirect."""
        import subprocess
        import sys

        code = (
            "import os, django;"
            "os.environ.setdefault('DJANGO_SETTINGS_MODULE','mailgen.settings');"
            "django.setup();"
            "from django.conf import settings as s;"
            "print(s.SESSION_COOKIE_SECURE, s.CSRF_COOKIE_SECURE, s.SECURE_SSL_REDIRECT)"
        )
        env = {**os.environ, "DJANGO_DEBUG": "0", "DJANGO_SECURE_SSL_REDIRECT": "1"}
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(settings.BASE_DIR),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "True True True")

    def test_csrf_and_session_cookies_are_strict(self):
        self.assertEqual(settings.CSRF_COOKIE_SAMESITE, "Strict")
        self.assertTrue(settings.SESSION_COOKIE_HTTPONLY)


class AdminStaticTests(SimpleTestCase):
    """Django admin CSS must be collectable and served by WhiteNoise on cPanel."""

    def test_whitenoise_middleware_is_installed_right_after_security(self):
        middleware = settings.MIDDLEWARE
        self.assertIn("whitenoise.middleware.WhiteNoiseMiddleware", middleware)
        self.assertEqual(
            middleware.index("whitenoise.middleware.WhiteNoiseMiddleware"),
            middleware.index("django.middleware.security.SecurityMiddleware") + 1,
        )

    def test_static_backend_uses_whitenoise(self):
        self.assertIn("whitenoise", settings.STORAGES["staticfiles"]["BACKEND"].lower())

    def test_admin_css_is_findable(self):
        self.assertIsNotNone(finders.find("admin/css/base.css"))
        self.assertIsNotNone(finders.find("admin/js/theme.js"))

    def test_admin_css_is_collectable(self):
        """The admin stylesheet must resolve to a real file the collector can copy."""
        found = finders.find("admin/css/base.css")
        self.assertIsNotNone(found)

        path = Path(found)
        self.assertTrue(path.exists())
        self.assertGreater(path.stat().st_size, 1000)
        self.assertIn(
            "django/contrib/admin/static",
            str(path).replace("\\", "/"),
            "admin CSS should come from Django's own static directory",
        )
