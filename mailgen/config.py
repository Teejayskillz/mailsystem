"""Configuration parsing and validation.

Deliberately free of Django imports so it can be unit-tested without loading
settings. ``mailgen.settings`` calls these helpers once at startup.

Supported URL forms
-------------------
DATABASE_URL
    mysql://user:pass@host:3306/dbname?charset=utf8mb4
    mysql+pymysql://user:pass@host/dbname
    mariadb://user:pass@host/dbname
    sqlite:///relative/path.db
    sqlite:////absolute/path.db
    sqlite://:memory:

MAILGEN_URL
    mailgen://example.com?prefix=otp-&length=10&forward_to=me@example.net
                       &max_addresses=10&quota_mb=100
    mailgen://?domain=example.com&...          (domain may also be a query parameter)

Credentials are never accepted inside MAILGEN_URL; cPanel and IMAP credentials
stay in their own variables.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qs, unquote, urlsplit

_LOGIN_DOMAIN = re.compile(
    r"^(?=.{4,190}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}$"
)
_LOCAL_PART = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{0,62}[a-z0-9])?$")
_PREFIX = re.compile(r"^[a-z0-9._-]{0,20}$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
_FERNET_KEY = re.compile(r"^[A-Za-z0-9_-]{43}=$")

DB_SCHEMES = {"mysql", "mysql+pymysql", "mariadb", "sqlite"}
MAILGEN_PARAMS = {"domain", "prefix", "length", "forward_to", "max_addresses", "quota_mb"}
MAILGEN_DEFAULTS: dict[str, Any] = {
    "domain": "",
    "prefix": "otp-",
    "length": 10,
    "forward_to": "",
    "max_addresses": 10,
    "quota_mb": 100,
}


class ConfigError(ValueError):
    """Raised for a malformed URL or value. Message is safe to display."""


# ---------------------------------------------------------------------------
# ALLOWED_HOSTS / CSRF_TRUSTED_ORIGINS normalisation
#
# These values are frequently pasted from regexes or logs ("www\.example\.com")
# or from JSON ("www\\.example.com"), which puts literal backslashes into the
# setting and makes every request fail with DisallowedHost. Normalisation strips
# the escaping, then validates strictly.
# ---------------------------------------------------------------------------
_HOST_ENTRY = re.compile(
    r"^(?:\*|(?:\*\.)?(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63})(?::\d{1,5})?$"
)
_IPV6_HOST_ENTRY = re.compile(r"^\[[0-9a-f:.]+\](?::\d{1,5})?$")
_ORIGIN_ENTRY = re.compile(
    r"^https?://(?:(?:\*\.)?[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?|\[[0-9a-f:.]+\])(?::\d{1,5})?$"
)


def normalize_hosts(raw: str, *, strict: bool = True) -> list[str]:
    """Turn a comma-separated host list into clean hostnames.

    Removes backslashes, quotes, whitespace and trailing dots. With
    ``strict=False`` invalid entries are dropped instead of raising, so a bad
    environment value can never take the site down.
    """
    hosts: list[str] = []

    for entry in _split_entries(raw):
        if _HOST_ENTRY.match(entry) or _IPV6_HOST_ENTRY.match(entry):
            hosts.append(entry)
        elif strict:
            raise ConfigError(
                f"invalid host entry {entry!r}; use plain hostnames such as "
                "'app.example.com' (no backslashes, schemes or paths)"
            )

    return _dedupe(hosts)


def normalize_origins(raw: str, *, strict: bool = True) -> list[str]:
    """Turn a comma-separated origin list into clean ``scheme://host[:port]``."""
    origins: list[str] = []

    for entry in _split_entries(raw):
        if _ORIGIN_ENTRY.match(entry):
            origins.append(entry)
        elif strict:
            raise ConfigError(
                f"invalid origin entry {entry!r}; expected https://host[:port] "
                "(no trailing slash, path or backslashes)"
            )

    return _dedupe(origins)


def _split_entries(raw: str) -> list[str]:
    entries: list[str] = []

    for part in (raw or "").split(","):
        entry = part.strip().strip('"').strip("'").strip()
        entry = entry.replace("\\", "").lower()
        entry = entry.rstrip("/").rstrip(".")
        if entry:
            entries.append(entry)

    return entries


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))



# ---------------------------------------------------------------------------
# DATABASE_URL
# ---------------------------------------------------------------------------
def parse_database_url(raw: str, base_dir: Path) -> dict[str, Any]:
    raw = (raw or "").strip()
    if not raw:
        raise ConfigError("DATABASE_URL is empty.")

    parts = urlsplit(raw)
    scheme = parts.scheme.lower()

    if scheme not in DB_SCHEMES:
        raise ConfigError(
            "unsupported scheme; use mysql://, mariadb:// or sqlite:///"
        )
    if parts.fragment:
        raise ConfigError("must not contain a #fragment")

    if scheme == "sqlite":
        return _sqlite_config(raw, parts, base_dir)

    if not parts.username:
        raise ConfigError("must include a database user")

    name = unquote(parts.path.lstrip("/"))
    if not name:
        raise ConfigError("must include a database name")

    try:
        port = parts.port
    except ValueError as exc:
        raise ConfigError("has an invalid port") from exc

    query = _single_values(parts.query, {"charset"}, "DATABASE_URL")
    charset = query.get("charset", "utf8mb4")
    if charset not in {"utf8mb4", "utf8"}:
        raise ConfigError("charset must be utf8mb4 or utf8")

    return {
        "ENGINE": "django.db.backends.mysql",
        "NAME": name,
        "USER": unquote(parts.username),
        "PASSWORD": unquote(parts.password or ""),
        "HOST": parts.hostname or "localhost",
        "PORT": str(port or 3306),
        "CONN_MAX_AGE": 60,
        "OPTIONS": {
            "charset": charset,
            "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
        },
        "TEST": {"CHARSET": "utf8mb4", "COLLATION": "utf8mb4_unicode_ci"},
    }


def _sqlite_config(raw: str, parts, base_dir: Path) -> dict[str, Any]:
    if raw in {"sqlite://:memory:", "sqlite:///:memory:"}:
        return {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}

    path = unquote(parts.path)
    if not path or path == "/":
        raise ConfigError("must include a file path for sqlite")

    if raw.startswith("sqlite:////"):
        # Four slashes = absolute path.
        candidate = Path(path)
    else:
        candidate = Path(path.lstrip("/"))
        if not candidate.is_absolute():
            candidate = base_dir / candidate

    return {"ENGINE": "django.db.backends.sqlite3", "NAME": str(candidate)}


# ---------------------------------------------------------------------------
# MAILGEN_URL
# ---------------------------------------------------------------------------
def parse_mailgen_url(raw: str) -> dict[str, Any]:
    raw = (raw or "").strip()
    if not raw:
        raise ConfigError("MAILGEN_URL is empty.")

    parts = urlsplit(raw)
    if parts.scheme.lower() != "mailgen":
        raise ConfigError("must start with mailgen://")

    if parts.username or parts.password:
        raise ConfigError(
            "must not embed credentials; keep CPANEL_* and IMAP_* variables separate"
        )
    if parts.fragment:
        raise ConfigError("must not contain a #fragment")
    if parts.path not in ("", "/"):
        raise ConfigError("must not contain a path; use query parameters")

    query = _single_values(parts.query, MAILGEN_PARAMS, "MAILGEN_URL")

    host = (parts.hostname or "").strip().lower()
    domain_param = (query.get("domain") or "").strip().lower()

    if host and domain_param and host != domain_param:
        raise ConfigError("domain is given twice (host and ?domain=) with different values")
    domain = domain_param or host

    result = dict(MAILGEN_DEFAULTS)
    result["domain"] = domain
    result["prefix"] = (query.get("prefix") if "prefix" in query else MAILGEN_DEFAULTS["prefix"]).lower()
    result["forward_to"] = (query.get("forward_to") or "").strip().lower()

    if "length" in query:
        result["length"] = _int_value("length", query["length"])
    if "max_addresses" in query:
        result["max_addresses"] = _int_value("max_addresses", query["max_addresses"])
    if "quota_mb" in query:
        result["quota_mb"] = _int_value("quota_mb", query["quota_mb"])

    return result


# ---------------------------------------------------------------------------
# Merge + validate
# ---------------------------------------------------------------------------
def resolve_mail_settings(env: Mapping[str, str]) -> dict[str, Any]:
    """Build the mail configuration from MAILGEN_URL plus legacy overrides.

    Precedence: explicit individual variables win over MAILGEN_URL values.
    """
    result = dict(MAILGEN_DEFAULTS)

    url = (env.get("MAILGEN_URL") or "").strip()
    if url:
        result.update(parse_mailgen_url(url))

    if (value := (env.get("MAILGEN_ADDRESS_DOMAIN") or "").strip()):
        result["domain"] = value.lower()
    if (value := (env.get("MAILGEN_ADDRESS_PREFIX") or "").strip()):
        result["prefix"] = value.lower()
    if (value := (env.get("MAILGEN_FORWARD_TO") or "").strip()):
        result["forward_to"] = value.lower()
    if (value := (env.get("MAILGEN_ADDRESS_LENGTH") or "").strip()):
        result["length"] = _int_value("MAILGEN_ADDRESS_LENGTH", value)
    if (value := (env.get("MAILGEN_MAX_ADDRESSES") or "").strip()):
        result["max_addresses"] = _int_value("MAILGEN_MAX_ADDRESSES", value)
    if (value := (env.get("MAILGEN_QUOTA_MB") or "").strip()):
        result["quota_mb"] = _int_value("MAILGEN_QUOTA_MB", value)

    return result


def validate_mail_settings(
    cfg: Mapping[str, Any], *, require_configured: bool = True
) -> list[str]:
    errors: list[str] = []

    domain = str(cfg.get("domain") or "")
    if not domain:
        if require_configured:
            errors.append(
                "No address domain configured. Use MAILGEN_URL=mailgen://example.com?..."
                " (or MAILGEN_ADDRESS_DOMAIN)."
            )
    elif not _LOGIN_DOMAIN.match(domain):
        errors.append(f"Address domain {domain!r} is not a valid domain name.")

    prefix = str(cfg.get("prefix", ""))
    if not _PREFIX.match(prefix):
        errors.append("Address prefix may only contain a-z, 0-9, '.', '_' and '-' (max 20).")

    length = cfg.get("length")
    if not isinstance(length, int) or not 6 <= length <= 40:
        errors.append("Address length must be an integer between 6 and 40.")

    forward_to = str(cfg.get("forward_to") or "")
    if not forward_to:
        if require_configured:
            errors.append(
                "No forwarding destination configured. Add forward_to=... to MAILGEN_URL."
            )
    elif not _EMAIL.match(forward_to):
        errors.append("Forwarding destination is not a valid email address.")

    max_addresses = cfg.get("max_addresses")
    if not isinstance(max_addresses, int) or not 1 <= max_addresses <= 200:
        errors.append("Maximum addresses must be an integer between 1 and 200.")

    quota = cfg.get("quota_mb")
    if not isinstance(quota, int) or not 1 <= quota <= 10240:
        errors.append("Mailbox quota must be an integer between 1 and 10240 MB.")

    return errors


def validate_core(
    *,
    debug: bool,
    secret_key: str,
    allowed_hosts: list[str],
    field_key: str,
    cpanel_base_url: str,
    imap_host: str,
) -> list[str]:
    errors: list[str] = []

    if not secret_key:
        errors.append("DJANGO_SECRET_KEY is not set.")
    elif not debug and len(secret_key) < 50:
        errors.append("DJANGO_SECRET_KEY is too short for production (use 50+ characters).")

    if not allowed_hosts:
        errors.append(
            "DJANGO_ALLOWED_HOSTS must list the dashboard host when DEBUG=0 "
            "(for example app.example.com)."
        )
    elif "*" in allowed_hosts and not debug:
        errors.append("DJANGO_ALLOWED_HOSTS must not contain '*' when DEBUG=0.")

    if field_key and not _FERNET_KEY.match(field_key):
        errors.append(
            "MAILGEN_FIELD_KEY is not a valid Fernet key "
            "(expected 44 url-safe base64 characters ending in '=')."
        )

    if cpanel_base_url:
        parts = urlsplit(cpanel_base_url)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            errors.append("CPANEL_BASE_URL must be an http(s) URL with a host.")
        elif parts.username or parts.password:
            errors.append("CPANEL_BASE_URL must not embed credentials.")
        elif parts.scheme == "http" and not debug:
            errors.append("CPANEL_BASE_URL must use https when DEBUG=0.")

    if imap_host and ("://" in imap_host or "/" in imap_host or " " in imap_host):
        errors.append("IMAP_HOST must be a bare hostname (no scheme, path or spaces).")

    return errors


def is_valid_fernet_key(value: str) -> bool:
    return bool(_FERNET_KEY.match(value or ""))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _single_values(query: str, allowed: set[str], label: str) -> dict[str, str]:
    parsed = parse_qs(query, keep_blank_values=True)

    unknown = sorted(set(parsed) - allowed)
    if unknown:
        raise ConfigError(
            f"has unsupported parameter(s): {', '.join(unknown)}. "
            f"Allowed: {', '.join(sorted(allowed))}"
        )

    values: dict[str, str] = {}
    for key, items in parsed.items():
        if len(items) > 1:
            raise ConfigError(f"repeats the {key!r} parameter")
        values[key] = items[0]

    return values


def _int_value(field: str, raw: str) -> int:
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{field} must be an integer") from exc
