"""Thin, typed client for the cPanel UAPI.

Only the endpoints needed by this MVP are wrapped. Every call verifies
``result.status == 1`` and raises :class:`CpanelError` with a message that is
safe to show to the signed-in administrator (never the token or the full URL).
"""

from __future__ import annotations

import logging
import time
from typing import Any

import requests
from django.conf import settings

logger = logging.getLogger("mailgen")

# cPanel error strings that simply mean "already gone" — safe to treat as success.
_ABSENT_MARKERS = (
    "does not exist",
    "no such",
    "not found",
)


class CpanelError(Exception):
    """A cPanel API failure with an administrator-safe message."""

    def __init__(self, message: str, *, status: int | None = None, permanent: bool = False):
        super().__init__(message)
        self.status = status
        self.permanent = permanent


class CpanelClient:
    def __init__(
        self,
        base_url: str = "",
        user: str = "",
        token: str = "",
        timeout: int = 25,
        verify_tls: bool = True,
        ca_bundle: str | None = None,
    ):
        self.base_url = (base_url or "").rstrip("/")
        self.user = user or ""
        self.token = token or ""
        self.timeout = timeout
        self.verify = ca_bundle or verify_tls
        self.ca_bundle = ca_bundle or None
        self.last_duration_ms: int | None = None
        self._session = requests.Session()
        self._session.headers.update({"Accept": "application/json"})

    @classmethod
    def from_settings(cls) -> "CpanelClient":
        return cls(
            base_url=getattr(settings, "CPANEL_BASE_URL", ""),
            user=getattr(settings, "CPANEL_USER", ""),
            token=getattr(settings, "CPANEL_TOKEN", ""),
            timeout=getattr(settings, "CPANEL_TIMEOUT", 25),
            verify_tls=getattr(settings, "CPANEL_VERIFY_TLS", True),
            ca_bundle=getattr(settings, "CPANEL_CA_BUNDLE", "") or None,
        )

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url and self.user and self.token)

    # -- transport --------------------------------------------------------
    def call(self, module: str, function: str, params: dict[str, Any] | None = None) -> Any:
        if not self.is_configured:
            raise CpanelError(
                "cPanel API is not configured (CPANEL_BASE_URL / CPANEL_USER / CPANEL_TOKEN).",
                permanent=True,
            )

        url = f"{self.base_url}/execute/{module}/{function}"
        started = time.monotonic()

        try:
            response = self._session.get(
                url,
                params=params or {},
                timeout=self.timeout,
                verify=self.verify,
                headers={"Authorization": f"cpanel {self.user}:{self.token}"},
            )
        except requests.RequestException as exc:
            raise CpanelError(
                f"cPanel API request failed ({type(exc).__name__}). "
                "Check outbound HTTPS access to the cPanel port from the server."
            ) from exc
        finally:
            self.last_duration_ms = int((time.monotonic() - started) * 1000)

        status = response.status_code

        if status in (401, 403):
            raise CpanelError(
                f"cPanel rejected the API token (HTTP {status}). "
                "Re-create the token and confirm the account name.",
                status=status,
                permanent=True,
            )

        if status >= 400:
            raise CpanelError(f"cPanel API returned HTTP {status}.", status=status)

        try:
            payload = response.json()
        except ValueError as exc:
            content_type = response.headers.get("Content-Type", "<unknown>")
            logger.warning(
                "cPanel returned non-JSON module=%s function=%s http=%s content_type=%r duration_ms=%s",
                module,
                function,
                status,
                content_type,
                self.last_duration_ms,
            )
            raise CpanelError(
                f"cPanel returned a non-JSON response for {module}::{function} "
                f"(HTTP {status}, Content-Type: {content_type}). "
                "An HTML login page here usually means the API token was rejected, "
                "the account requires MFA, or the endpoint is wrong.",
                status=status,
                permanent=True,
            ) from exc

        result = self._unwrap(payload)

        try:
            result_status = int(result.get("status", 0))
        except (TypeError, ValueError):
            result_status = 0

        if result_status != 1:
            detail = self._describe_failure(result)
            logger.warning(
                "cPanel API error module=%s function=%s http=%s status=%r "
                "errors=%r messages=%r warnings=%r content_type=%r duration_ms=%s",
                module,
                function,
                status,
                result.get("status"),
                result.get("errors"),
                result.get("messages"),
                result.get("warnings"),
                response.headers.get("Content-Type", ""),
                self.last_duration_ms,
            )
            raise CpanelError(
                f"cPanel API error in {module}::{function} (HTTP {status}): {detail}",
                status=status,
                permanent=True,
            )

        logger.debug(
            "cPanel API ok module=%s function=%s http=%s duration_ms=%s",
            module,
            function,
            status,
            self.last_duration_ms,
        )

        return result.get("data")

    # -- response shapes --------------------------------------------------
    @staticmethod
    def _unwrap(payload: Any) -> dict[str, Any]:
        """Return the UAPI result object from either envelope shape.

        Standard cPanel: {"result": {"status": 1, "data": ...}}
        Some cPanel builds/proxies (observed on s44.srvx.ws): a *flat* envelope
        {"status": 1, "data": ..., "errors": null, "messages": null}
        without the "result" wrapper.
        """
        if not isinstance(payload, dict):
            return {}

        result = payload.get("result")
        if isinstance(result, dict):
            return result

        if "status" in payload:
            return payload

        return {}

    @staticmethod
    def _describe_failure(result: dict[str, Any]) -> str:
        parts: list[str] = []

        for key in ("errors", "messages", "warnings"):
            value = result.get(key)
            if isinstance(value, (list, tuple)):
                parts.extend(str(item).strip() for item in value if str(item).strip())
            elif value:
                parts.append(str(value).strip())

        detail = "; ".join(part for part in parts if part)[:400]
        if detail:
            return detail

        return (
            f"status={result.get('status')!r} with no error text from cPanel. "
            "This usually means the Email module is unavailable for the account "
            "or its 'Receive Mail' role is restricted."
        )

    # -- helpers ----------------------------------------------------------
    @staticmethod
    def _as_list(data: Any) -> list[dict[str, Any]]:
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            return [data]
        return []

    # -- read -------------------------------------------------------------
    def list_pops(self) -> list[dict[str, Any]]:
        return self._as_list(self.call("Email", "list_pops"))

    def list_mail_domains(self) -> list[str]:
        data = self.call("Email", "list_mail_domains")
        domains: list[str] = []
        for item in self._as_list(data):
            value = item.get("domain")
            if isinstance(value, str) and value:
                domains.append(value.lower())
        if not domains and isinstance(data, list):
            domains = [str(v).lower() for v in data if isinstance(v, str)]
        return sorted(set(domains))

    def list_forwarders(self, domain: str) -> list[dict[str, Any]]:
        return self._as_list(self.call("Email", "list_forwarders", {"domain": domain}))

    def mailbox_exists(self, email: str) -> bool:
        email = email.lower()
        return any(
            str(pop.get("email", "")).lower() == email for pop in self.list_pops()
        )

    def is_suspended_incoming(self, email: str) -> bool:
        email = email.lower()
        for pop in self.list_pops():
            if str(pop.get("email", "")).lower() == email:
                return bool(int(pop.get("suspended_incoming", 0) or 0))
        return False

    def forwarder_targets(self, address: str) -> list[str]:
        """All destinations currently configured for ``address``."""
        domain = address.split("@", 1)[-1]
        targets: list[str] = []
        for row in self.list_forwarders(domain):
            if str(row.get("dest", "")).lower() == address.lower():
                forward = str(row.get("forward", "")).strip()
                if forward:
                    targets.append(forward)
        return targets

    def forwarder_exists(self, address: str, destination: str) -> bool:
        destination = destination.lower()
        return any(t.lower() == destination for t in self.forwarder_targets(address))

    # -- write ------------------------------------------------------------
    def add_pop(self, email: str, password: str, quota_mb: int = 100) -> None:
        local, _, domain = email.partition("@")
        self.call(
            "Email",
            "add_pop",
            {
                "email": email,
                "password": password,
                "domain": domain or local,
                "quota": str(int(quota_mb)),
                "send_welcome_email": "0",
            },
        )

    def delete_pop(self, email: str) -> None:
        _local, _, domain = email.partition("@")
        try:
            self.call("Email", "delete_pop", {"email": email, "domain": domain})
        except CpanelError as exc:
            if not _is_absent_error(exc):
                raise

    def add_forwarder(self, address: str, destination: str) -> None:
        _local, _, domain = address.partition("@")
        self.call(
            "Email",
            "add_forwarder",
            {
                "domain": domain,
                "email": address,
                "fwdopt": "fwd",
                "fwdemail": destination,
            },
        )

    def delete_forwarder(self, address: str, destination: str) -> None:
        try:
            self.call(
                "Email",
                "delete_forwarder",
                {"address": address, "forwarder": destination},
            )
        except CpanelError as exc:
            if not _is_absent_error(exc):
                raise

    def suspend_incoming(self, email: str) -> None:
        self.call("Email", "suspend_incoming", {"email": email})

    def unsuspend_incoming(self, email: str) -> None:
        self.call("Email", "unsuspend_incoming", {"email": email})


def _is_absent_error(exc: CpanelError) -> bool:
    message = str(exc).lower()
    return any(marker in message for marker in _ABSENT_MARKERS)
