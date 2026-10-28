from __future__ import annotations

import logging

from django.conf import settings
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.utils import timezone

logger = logging.getLogger("mailgen")


class HostHeaderSanitizerMiddleware:
    """Remove backslashes from the Host header before host validation runs.

    A proxy, control panel or hand-edited vhost that escapes dots
    (``www\.example\.com``) reaches Django as an illegal host and every request
    fails with ``DisallowedHost``. Backslashes are never valid in a Host header,
    so stripping them cannot weaken host validation: Django still checks the
    cleaned value against ``ALLOWED_HOSTS``.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host = request.META.get("HTTP_HOST", "")
        if "\\" in host:
            cleaned = host.replace("\\", "").strip()
            logger.warning(
                "host header contained backslashes; sanitised original=%r cleaned=%r path=%s",
                host,
                cleaned,
                request.META.get("PATH_INFO", ""),
            )
            request.META["HTTP_HOST"] = cleaned

        server_name = request.META.get("SERVER_NAME", "")
        if "\\" in server_name:
            request.META["SERVER_NAME"] = server_name.replace("\\", "").strip()

        return self.get_response(request)

CSP = (
    "default-src 'self'; "
    "img-src 'self' data:; "
    "style-src 'self'; "
    "script-src 'self'; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "frame-src 'self'; "
    "object-src 'none'; "
    "base-uri 'none'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)


class SecurityHeadersMiddleware:
    """Adds a strict CSP plus a few headers Django does not set itself."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        if not response.has_header("Content-Security-Policy"):
            response.headers["Content-Security-Policy"] = CSP
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")

        return response


class SessionIdleTimeoutMiddleware:
    """Logs the administrator out after a period of inactivity."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.idle_seconds = int(getattr(settings, "MAILGEN_SESSION_IDLE_SECONDS", 1800))

    def __call__(self, request):
        if request.user.is_authenticated:
            last_seen = request.session.get("_last_seen")
            now = int(timezone.now().timestamp())

            if last_seen and now - int(last_seen) > self.idle_seconds:
                logout(request)
                request.session.flush()
                return redirect("/login/?reason=idle")

            request.session["_last_seen"] = now

        return self.get_response(request)
