"""Fernet-based field encryption for mailbox passwords.

The key is separate from SECRET_KEY so that rotating sessions/secrets does not
destroy stored mailbox credentials, and vice versa.
"""

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


class DecryptionError(Exception):
    """Raised when a stored secret cannot be decrypted with the configured key."""


class FieldCipher:
    def __init__(self, key: str):
        if not key:
            raise ImproperlyConfigured(
                "MAILGEN_FIELD_KEY is not set. Generate one with: "
                "python manage.py generate_field_key"
            )
        try:
            self._fernet = Fernet(key.encode("ascii"))
        except (ValueError, TypeError) as exc:
            raise ImproperlyConfigured(
                "MAILGEN_FIELD_KEY must be a url-safe base64-encoded 32-byte key "
                "(generate one with: python manage.py generate_field_key)."
            ) from exc

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError, TypeError) as exc:
            raise DecryptionError(
                "Stored mailbox password cannot be decrypted. The MAILGEN_FIELD_KEY "
                "may have changed."
            ) from exc


@lru_cache(maxsize=1)
def get_cipher() -> FieldCipher:
    return FieldCipher(getattr(settings, "MAILGEN_FIELD_KEY", ""))


def generate_field_key() -> str:
    return Fernet.generate_key().decode("ascii")
