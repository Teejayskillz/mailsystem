"""Read-only hosting/integration health checks.

Every check returns an explicit status and the evidence behind it. Nothing here
mutates cPanel, DNS or mailboxes.
"""

from __future__ import annotations

import platform
import socket
from dataclasses import dataclass, field

import dns.exception
import dns.resolver
from django.conf import settings
from django.db import connection

from ..models import Address
from .cpanel import CpanelClient, CpanelError
from .crypto import DecryptionError
from .imap import ImapError, ImapService

OK = "ok"
WARN = "warn"
FAIL = "fail"
SKIP = "skip"


@dataclass
class Check:
    key: str
    label: str
    status: str
    detail: str
    evidence: list[str] = field(default_factory=list)


def collect_checks(include_network: bool = True) -> list[Check]:
    checks: list[Check] = []
    checks.extend(_runtime_checks())
    checks.extend(_database_checks())
    checks.extend(_security_checks())
    checks.extend(_configuration_checks())
    if include_network:
        checks.extend(_cpanel_checks())
        checks.extend(_dns_checks())
        checks.extend(_imap_checks())
    checks.extend(_capacity_checks())
    return checks


# ---------------------------------------------------------------------------
# Local checks
# ---------------------------------------------------------------------------
def _runtime_checks() -> list[Check]:
    import django

    checks = [
        Check(
            "python",
            "Python runtime",
            OK if platform.python_version_tuple() >= ("3", "10") else FAIL,
            f"Python {platform.python_version()} on {platform.system()}",
            [platform.platform()],
        ),
        Check("django", "Django version", OK, f"Django {django.get_version()}", []),
    ]

    if settings.DEBUG:
        checks.append(Check("debug", "DEBUG disabled", FAIL, "DEBUG=True — never run this way in production."))
    else:
        checks.append(Check("debug", "DEBUG disabled", OK, "DEBUG=False."))

    secret = getattr(settings, "SECRET_KEY", "")
    if not secret or secret.startswith("dev-only-insecure"):
        checks.append(Check("secret_key", "Secret key", FAIL, "DJANGO_SECRET_KEY is missing or a development fallback."))
    else:
        checks.append(Check("secret_key", "Secret key", OK, f"Configured ({len(secret)} chars)."))

    key = getattr(settings, "MAILGEN_FIELD_KEY", "")
    checks.append(
        Check(
            "field_key",
            "Mailbox password key",
            OK if key else FAIL,
            "MAILGEN_FIELD_KEY is configured." if key else "MAILGEN_FIELD_KEY is missing — mailbox passwords cannot be stored.",
        )
    )

    env_file = getattr(settings, "ENV_FILE", "")
    if env_file:
        checks.append(
            Check("env_file", "Environment file", WARN, f"Loaded from {env_file}. Confirm it is outside the document root and mode 600.")
        )
    return checks


def _database_checks() -> list[Check]:
    vendor = connection.vendor
    version = "unknown"
    try:
        with connection.cursor() as cursor:
            if vendor == "mysql":
                cursor.execute("SELECT VERSION()")
            else:
                cursor.execute("SELECT sqlite_version()")
            version = str(cursor.fetchone()[0])
    except Exception:
        version = "unavailable"

    tables = set(connection.introspection.table_names())
    has_tables = {"generator_address", "generator_message"}.issubset(tables)

    return [
        Check("db_engine", "Database engine", OK if vendor in {"mysql", "sqlite"} else WARN, f"{vendor} {version}"),
        Check(
            "db_schema",
            "Database schema",
            OK if has_tables else FAIL,
            "Required tables are present." if has_tables else "Run `python manage.py migrate`.",
        ),
    ]


def _security_checks() -> list[Check]:
    checks = []
    if settings.DEBUG:
        checks.append(Check("cookies", "Session cookie flags", WARN, "Secure flags are disabled while DEBUG=True."))
    else:
        ok = settings.SESSION_COOKIE_SECURE and settings.CSRF_COOKIE_SECURE
        checks.append(
            Check(
                "cookies",
                "Session cookie flags",
                OK if ok else FAIL,
                f"secure={settings.SESSION_COOKIE_SECURE}, httponly={settings.SESSION_COOKIE_HTTPONLY}, "
                f"samesite={settings.SESSION_COOKIE_SAMESITE}",
            )
        )

    checks.append(
        Check(
            "allowed_hosts",
            "Allowed hosts",
            OK if settings.ALLOWED_HOSTS and "*" not in settings.ALLOWED_HOSTS else WARN,
            ", ".join(settings.ALLOWED_HOSTS) or "empty",
        )
    )
    checks.append(
        Check(
            "xframe",
            "Clickjacking protection",
            OK if settings.X_FRAME_OPTIONS == "DENY" else WARN,
            f"X_FRAME_OPTIONS={settings.X_FRAME_OPTIONS}",
        )
    )
    return checks


def _configuration_checks() -> list[Check]:
    domain = getattr(settings, "MAILGEN_ADDRESS_DOMAIN", "") or ""
    forward_to = getattr(settings, "MAILGEN_FORWARD_TO", "") or ""
    return [
        Check("address_domain", "Address domain", OK if domain else FAIL, domain or "MAILGEN_ADDRESS_DOMAIN is not set."),
        Check("forward_to", "Forwarding target", OK if forward_to else FAIL, forward_to or "MAILGEN_FORWARD_TO is not set."),
        Check(
            "quota",
            "Mailbox quota",
            OK,
            f"{getattr(settings, 'MAILGEN_QUOTA_MB', 100)} MB per generated mailbox",
        ),
    ]


# ---------------------------------------------------------------------------
# Network checks (read-only)
# ---------------------------------------------------------------------------
def _cpanel_checks() -> list[Check]:
    client = CpanelClient.from_settings()
    checks: list[Check] = []

    if not client.is_configured:
        return [
            Check("cpanel_config", "cPanel API credentials", FAIL, "CPANEL_BASE_URL/USER/TOKEN are not all set."),
        ]

    try:
        domains = client.list_mail_domains()
        elapsed = client.last_duration_ms
        checks.append(
            Check(
                "cpanel_api",
                "cPanel API token",
                OK,
                f"Token accepted ({elapsed} ms).",
                [f"Mail domains: {', '.join(domains) or 'none'}"],
            )
        )
    except CpanelError as exc:
        return [Check("cpanel_api", "cPanel API token", FAIL, str(exc))]

    configured_domain = (getattr(settings, "MAILGEN_ADDRESS_DOMAIN", "") or "").lower()
    checks.append(
        Check(
            "cpanel_mail_domain",
            "Configured domain is a mail domain",
            OK if configured_domain in domains else FAIL,
            configured_domain if configured_domain in domains else (
                f"{configured_domain or '(none)'} is not listed by cPanel; MX/routing is probably not local."
            ),
            [f"cPanel knows: {', '.join(domains)}"] if domains else [],
        )
    )

    try:
        pops = client.list_pops()
        checks.append(
            Check("cpanel_mailboxes", "Mailboxes visible", OK, f"{len(pops)} mailbox(es) on the account.")
        )
    except CpanelError as exc:
        checks.append(Check("cpanel_mailboxes", "Mailboxes visible", WARN, str(exc)))

    if configured_domain:
        try:
            forwards = client.list_forwarders(configured_domain)
            checks.append(
                Check(
                    "cpanel_forwarders",
                    "Forwarders visible",
                    OK,
                    f"{len(forwards)} forwarder(s) on {configured_domain}.",
                )
            )
        except CpanelError as exc:
            checks.append(Check("cpanel_forwarders", "Forwarders visible", WARN, str(exc)))

    return checks


def _dns_checks() -> list[Check]:
    domain = getattr(settings, "MAILGEN_ADDRESS_DOMAIN", "") or ""
    checks: list[Check] = []
    if not domain:
        return [Check("dns", "DNS / MX", SKIP, "No address domain configured.")]

    try:
        answers = dns.resolver.resolve(domain, "MX", lifetime=8)
        records = sorted(f"{r.preference} {r.exchange}" for r in answers)
        if any(str(r.exchange).rstrip(".") == "" for r in answers):
            checks.append(
                Check(
                    "dns_mx",
                    "MX records",
                    FAIL,
                    "The domain publishes a null MX (0 .): it does not accept email.",
                    records,
                )
            )
        else:
            checks.append(Check("dns_mx", "MX records", OK, "; ".join(records), records))
    except Exception as exc:
        checks.append(Check("dns_mx", "MX records", FAIL, f"MX lookup failed: {type(exc).__name__}"))

    imap_host = getattr(settings, "IMAP_HOST", "") or ""
    if imap_host:
        try:
            infos = socket.getaddrinfo(imap_host, None)
            addresses = sorted({info[4][0] for info in infos})
            checks.append(Check("dns_imap", "IMAP host resolves", OK, ", ".join(addresses[:4]), addresses[:4]))
        except OSError as exc:
            checks.append(Check("dns_imap", "IMAP host resolves", FAIL, f"Could not resolve {imap_host}: {exc}"))
    return checks


def _imap_checks() -> list[Check]:
    service = ImapService()
    if not service.is_configured:
        return [Check("imap_config", "IMAP configuration", FAIL, "IMAP_HOST is not set.")]

    checks: list[Check] = [
        Check("imap_config", "IMAP configuration", OK, f"{service.host}:{service.port} ({service.encryption})")
    ]

    addresses = Address.objects.live().exclude(status=Address.Status.FAILED).order_by("-created_at")[:3]
    if not addresses:
        checks.append(Check("imap_login", "IMAP login", SKIP, "No addresses to test yet."))
        return checks

    for address in addresses:
        try:
            service.verify(address)
            checks.append(Check(f"imap_{address.pk}", f"IMAP login — {address.address}", OK, "Login and INBOX select succeeded."))
        except (ImapError, DecryptionError) as exc:
            checks.append(Check(f"imap_{address.pk}", f"IMAP login — {address.address}", FAIL, str(exc)))

    return checks


def _capacity_checks() -> list[Check]:
    live = Address.objects.live().count()
    maximum = int(getattr(settings, "MAILGEN_MAX_ADDRESSES", 10))
    return [
        Check(
            "capacity",
            "Address capacity",
            OK if live < maximum else WARN,
            f"{live} of {maximum} configured addresses in use.",
        )
    ]
