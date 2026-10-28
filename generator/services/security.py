"""Rate limiting and login auditing.

Django's cache is per-process on cPanel/Passenger, so counters live in the
database instead. Fixed windows are enough for a single-administrator tool.
"""

from __future__ import annotations

import hashlib
import time

from django.db import IntegrityError, transaction

from ..models import LoginAttempt, Throttle


def client_ip(request) -> str:
    """REMOTE_ADDR only: cPanel/Passenger passes the real client address.

    X-Forwarded-For is intentionally ignored — it is client-controlled unless a
    trusted proxy is known to rewrite it.
    """
    return (request.META.get("REMOTE_ADDR") or "0.0.0.0")[:45]


class RateLimiter:
    @staticmethod
    def _key_hash(key: str) -> str:
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    @classmethod
    def hit(cls, bucket: str, key: str, limit: int, window_seconds: int) -> tuple[bool, int]:
        """Increment ``bucket``/``key`` and report whether the call is allowed.

        Returns ``(allowed, retry_after_seconds)``.
        """
        now = int(time.time())
        window_seconds = max(1, int(window_seconds))
        window_start = now - (now % window_seconds)
        key_hash = cls._key_hash(f"{bucket}:{key}")

        with transaction.atomic():
            row = (
                Throttle.objects.select_for_update()
                .filter(bucket=bucket, key_hash=key_hash)
                .first()
            )

            if row is None:
                try:
                    row = Throttle.objects.create(
                        bucket=bucket, key_hash=key_hash, window_start=window_start, counter=1
                    )
                except IntegrityError:
                    row = (
                        Throttle.objects.select_for_update()
                        .filter(bucket=bucket, key_hash=key_hash)
                        .first()
                    )
                    if row is None:  # pragma: no cover - defensive
                        return True, 0
                    row.counter += 1
                    row.save(update_fields=["counter"])
            else:
                if row.window_start != window_start:
                    row.window_start = window_start
                    row.counter = 0
                row.counter += 1
                row.save(update_fields=["window_start", "counter"])

        allowed = row.counter <= limit
        retry_after = max(0, window_start + window_seconds - now) if not allowed else 0
        return allowed, retry_after

    @classmethod
    def record_login(cls, ip: str, username: str, ok: bool) -> None:
        LoginAttempt.objects.create(ip=ip[:45], username=username[:150], ok=ok)
