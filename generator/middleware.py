from __future__ import annotations

from django.conf import settings
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.utils import timezone

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
