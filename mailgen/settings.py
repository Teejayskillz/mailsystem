"""
Django settings for the Personal Email Generator (MVP v2).

Secrets come from the environment (or an env file outside the web root).
Nothing sensitive is hard-coded here.
"""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
# Production: point MAILGEN_ENV_FILE at a file OUTSIDE the document root,
# e.g. /home/USER/.mailgen/env (chmod 600).
ENV_FILE = os.environ.get("MAILGEN_ENV_FILE", str(BASE_DIR / ".env"))
if os.path.exists(ENV_FILE):
    load_dotenv(ENV_FILE, override=False)


def env(key: str, default: str | None = None) -> str | None:
    value = os.environ.get(key)
    return value if value not in (None, "") else default


def env_bool(key: str, default: bool = False) -> bool:
    value = env(key)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(key: str, default: int) -> int:
    try:
        return int(env(key, str(default)) or default)
    except (TypeError, ValueError):
        return default


def env_list(key: str, default: str = "") -> list[str]:
    raw = env(key, default) or ""
    return [item.strip() for item in raw.split(",") if item.strip()]


DEBUG = env_bool("DJANGO_DEBUG", False)

SECRET_KEY = env("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "dev-only-insecure-key-do-not-use-in-production-0000000000"
    else:
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY is required. Set it in the environment or in MAILGEN_ENV_FILE."
        )

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS", "")

# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "generator",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "generator.middleware.SecurityHeadersMiddleware",
    "generator.middleware.SessionIdleTimeoutMiddleware",
]

ROOT_URLCONF = "mailgen.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "mailgen.wsgi.application"

# ---------------------------------------------------------------------------
# Database — MySQL/MariaDB (cPanel), SQLite only for throwaway local runs
# ---------------------------------------------------------------------------
DB_ENGINE = (env("DB_ENGINE", "mysql") or "mysql").lower()

if DB_ENGINE == "sqlite":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": env("DB_NAME", str(BASE_DIR / "db.sqlite3")),
        }
    }
else:
    try:
        import pymysql

        pymysql.install_as_MySQLdb()
    except ImportError as exc:  # pragma: no cover - deployment guard
        raise ImproperlyConfigured(
            "PyMySQL is required for MySQL. Install it or set DB_ENGINE=sqlite."
        ) from exc

    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": env("DB_NAME", ""),
            "USER": env("DB_USER", ""),
            "PASSWORD": env("DB_PASSWORD", ""),
            "HOST": env("DB_HOST", "localhost"),
            "PORT": env("DB_PORT", "3306"),
            "OPTIONS": {
                "charset": "utf8mb4",
                "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
            },
            "CONN_MAX_AGE": 60,
            "TEST": {"CHARSET": "utf8mb4", "COLLATION": "utf8mb4_unicode_ci"},
        }
    }

# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/login/"

# Any accidental mail sending would be a bug in this MVP.
EMAIL_BACKEND = "django.core.mail.backends.dummy.EmailBackend"

# ---------------------------------------------------------------------------
# Sessions / cookies
# ---------------------------------------------------------------------------
SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_NAME = env("SESSION_COOKIE_NAME", "mailgen_session")
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Strict"
SESSION_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_AGE = env_int("MAILGEN_SESSION_ABSOLUTE_SECONDS", 43200)  # 12h
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = False

MAILGEN_SESSION_IDLE_SECONDS = env_int("MAILGEN_SESSION_IDLE_SECONDS", 1800)  # 30 min

CSRF_COOKIE_SAMESITE = "Strict"
CSRF_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_HTTPONLY = False  # JS reads the token from a meta tag, not the cookie
CSRF_FAILURE_VIEW = "generator.views.csrf_failure"

# ---------------------------------------------------------------------------
# Transport / browser hardening
# ---------------------------------------------------------------------------
SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", not DEBUG)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "no-referrer"
SECURE_HSTS_SECONDS = env_int("DJANGO_HSTS_SECONDS", 0)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("DJANGO_HSTS_SUBDOMAINS", False)
SECURE_HSTS_PRELOAD = False
X_FRAME_OPTIONS = "DENY"

# ---------------------------------------------------------------------------
# Static files (Bootstrap is vendored — no CDN, CSP stays strict)
# ---------------------------------------------------------------------------
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"] if (BASE_DIR / "static").exists() else []
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Application configuration (all optional values have safe defaults)
# ---------------------------------------------------------------------------
MAILGEN_ADDRESS_DOMAIN = env("MAILGEN_ADDRESS_DOMAIN", "")
MAILGEN_ADDRESS_PREFIX = env("MAILGEN_ADDRESS_PREFIX", "otp-")
MAILGEN_ADDRESS_LENGTH = env_int("MAILGEN_ADDRESS_LENGTH", 10)
MAILGEN_FORWARD_TO = env("MAILGEN_FORWARD_TO", "")
MAILGEN_MAX_ADDRESSES = env_int("MAILGEN_MAX_ADDRESSES", 10)
MAILGEN_QUOTA_MB = env_int("MAILGEN_QUOTA_MB", 100)

# Fernet key (urlsafe base64, 32 bytes) used to encrypt mailbox passwords at rest.
MAILGEN_FIELD_KEY = env("MAILGEN_FIELD_KEY", "")

CPANEL_BASE_URL = env("CPANEL_BASE_URL", "")
CPANEL_USER = env("CPANEL_USER", "")
CPANEL_TOKEN = env("CPANEL_TOKEN", "")
CPANEL_TIMEOUT = env_int("CPANEL_TIMEOUT", 25)
CPANEL_VERIFY_TLS = env_bool("CPANEL_VERIFY_TLS", True)
CPANEL_CA_BUNDLE = env("CPANEL_CA_BUNDLE", "")

IMAP_HOST = env("IMAP_HOST", "")
IMAP_PORT = env_int("IMAP_PORT", 993)
IMAP_ENCRYPTION = env("IMAP_ENCRYPTION", "ssl")  # ssl (993) or starttls (143)
IMAP_TIMEOUT = env_int("IMAP_TIMEOUT", 25)
IMAP_VALIDATE_CERT = env_bool("IMAP_VALIDATE_CERT", True)
IMAP_SYNC_BATCH = env_int("IMAP_SYNC_BATCH", 5)
IMAP_MAX_MESSAGES = env_int("IMAP_MAX_MESSAGES", 100)

MAILGEN_LOGIN_MAX_ATTEMPTS = env_int("MAILGEN_LOGIN_MAX_ATTEMPTS", 5)
MAILGEN_LOGIN_WINDOW_SECONDS = env_int("MAILGEN_LOGIN_WINDOW_SECONDS", 900)

# ---------------------------------------------------------------------------
# Logging — outside the document root on cPanel (project root, not /public)
# ---------------------------------------------------------------------------
LOG_DIR = Path(env("MAILGEN_LOG_DIR", str(BASE_DIR / "logs")))
LOG_DIR.mkdir(parents=True, exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"},
    },
    "handlers": {
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(LOG_DIR / "app.log"),
            "maxBytes": 2 * 1024 * 1024,
            "backupCount": 3,
            "formatter": "standard",
            "encoding": "utf-8",
        },
        "console": {"class": "logging.StreamHandler", "formatter": "standard"},
    },
    "root": {"handlers": ["file", "console"], "level": "INFO"},
    "loggers": {
        "django.request": {"handlers": ["file"], "level": "WARNING", "propagate": False},
        "mailgen": {"handlers": ["file", "console"], "level": "INFO", "propagate": False},
    },
}
