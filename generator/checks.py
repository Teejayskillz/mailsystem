"""Django system checks for optional integrations.

Missing mail/cPanel/IMAP configuration does not stop the app from booting (the
diagnostics page is how you fix it), but it should be visible in
``manage.py check`` and ``check --deploy`` rather than failing silently.
"""

from django.conf import settings
from django.core.checks import Error, Tags, Warning, register


@register(Tags.security)
def field_key_check(app_configs, **kwargs):
    if not getattr(settings, "MAILGEN_FIELD_KEY", ""):
        return [
            Error(
                "MAILGEN_FIELD_KEY is not set: mailbox passwords cannot be encrypted.",
                hint="Run: python manage.py generate_field_key",
                id="generator.E001",
            )
        ]
    return []


@register(Tags.compatibility)
def integrations_check(app_configs, **kwargs):
    messages = []

    if not all(
        (
            getattr(settings, "CPANEL_BASE_URL", ""),
            getattr(settings, "CPANEL_USER", ""),
            getattr(settings, "CPANEL_TOKEN", ""),
        )
    ):
        messages.append(
            Warning(
                "cPanel API is not fully configured; addresses cannot be provisioned.",
                hint="Set CPANEL_BASE_URL, CPANEL_USER and CPANEL_TOKEN.",
                id="generator.W001",
            )
        )

    if not getattr(settings, "IMAP_HOST", ""):
        messages.append(
            Warning(
                "IMAP_HOST is not configured; messages cannot be read.",
                hint="Set IMAP_HOST to the mail server hostname.",
                id="generator.W002",
            )
        )

    return messages
