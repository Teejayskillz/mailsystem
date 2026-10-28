# Personal Email Generator (Django MVP v2)

A private, single-administrator tool for generating throwaway addresses on **your own**
cPanel domain. Each address is a **real cPanel mailbox** with a **real forwarder** to your
primary inbox, and the dashboard reads it over IMAP.

> See [`docs/VERIFICATION.md`](docs/VERIFICATION.md) for exactly what has been tested and
> what still requires your hosting.

## What it does

- Single-admin login (Django auth, no public registration, rate-limited).
- Generates random addresses (`otp-xxxxxxxxxx@example.com`) on your configured domain.
- Creates the mailbox and forwarder through the cPanel UAPI, then **re-reads server state**
  to verify both exist.
- Lists addresses with three separate evidence levels:
  - **Configured** – mailbox + forwarder confirmed in cPanel
  - **Inbox-capable** – IMAP login and `INBOX` select succeeded
  - **Delivery-tested** – an external sender's message was actually fetched
- Incremental IMAP sync, message list, and a sandboxed message viewer that shows
  verification codes as plain text.
- Enable / disable / delete with server-state verification.
- Protected diagnostics page.

## What it deliberately does not do

No sending or replying, no attachments, no OTP extraction or storage, no catch-all
changes, no domain default-address changes, no multi-user, no background worker.

## Requirements

- Python **3.10+** (Django 5.2 LTS; Python 3.11/3.12 recommended)
- MySQL/MariaDB on cPanel (SQLite only for throwaway local runs)
- cPanel account with *Email Accounts*, *Forwarders* and *Manage API Tokens*
- Local mail routing for the address domain (MX → this server)
- IMAP over TLS (993) reachable from the server

## Configuration

Only a handful of values are required. Database and address policy each fit on one line:

| Variable | Purpose | Example |
|---|---|---|
| `DJANGO_SECRET_KEY` | session/CSRF signing | 50+ random characters |
| `DATABASE_URL` | database | `mysql://user:pass@localhost:3306/db?charset=utf8mb4` |
| `MAILGEN_URL` | address policy | `mailgen://example.com?prefix=otp-&length=10&forward_to=me@example.net&max_addresses=10&quota_mb=100` |
| `MAILGEN_FIELD_KEY` | encrypts mailbox passwords | output of `manage.py generate_field_key` |
| `CPANEL_BASE_URL` | cPanel API endpoint | `https://server.example.com:2083` |
| `CPANEL_USER` | cPanel account | `cpuser` |
| `CPANEL_TOKEN` | API token | from cPanel » Security » Manage API Tokens |
| `IMAP_HOST` | mail server hostname | `mail.example.com` |
| `DJANGO_ALLOWED_HOSTS` | optional extra hosts (normalised) | `app.example.com` |

This deployment hard-codes `mailsystem.nzdworld.com` and `www.mailsystem.nzdworld.com` in
`ALLOWED_HOSTS`, and both `https://` origins in `CSRF_TRUSTED_ORIGINS`, so a mis-escaped
environment value cannot break login again. If the domain changes, update the
`HARDCODED_HOSTS` / `HARDCODED_CSRF_ORIGINS` constants in `mailgen/settings.py`.

### `DATABASE_URL`

```
mysql://user:password@host:3306/dbname?charset=utf8mb4
mysql+pymysql://user:password@host/dbname
mariadb://user:password@host/dbname
sqlite:///relative.db          # local only
sqlite:////absolute/path.db
sqlite://:memory:
```

Credentials are percent-decoded, so `p%40ss` becomes `p@ss`. The only supported query
parameter is `charset` (`utf8mb4` or `utf8`); anything else is rejected so typos surface
immediately.

### `MAILGEN_URL`

```
mailgen://example.com?prefix=otp-&length=10&forward_to=primary@example.com&max_addresses=10&quota_mb=100
mailgen://?domain=example.com&forward_to=primary@example.com     # domain as a parameter
```

| Parameter | Meaning | Default | Bounds |
|---|---|---|---|
| `domain` (or URL host) | domain for generated addresses | — | valid domain |
| `prefix` | local-part prefix | `otp-` | `[a-z0-9._-]{0,20}` |
| `length` | random characters after the prefix | `10` | 6–40 |
| `forward_to` | your primary inbox | — | valid email |
| `max_addresses` | cap on live addresses | `10` | 1–200 |
| `quota_mb` | per-mailbox quota | `100` | 1–10240 |

The scheme must be `mailgen://`, credentials are refused, and unknown parameters are
rejected (`forwad_to` fails loudly instead of being ignored).

### Compatibility

The earlier individual variables still work and take precedence over `MAILGEN_URL`:
`MAILGEN_ADDRESS_DOMAIN`, `MAILGEN_ADDRESS_PREFIX`, `MAILGEN_ADDRESS_LENGTH`,
`MAILGEN_FORWARD_TO`, `MAILGEN_MAX_ADDRESSES`, `MAILGEN_QUOTA_MB`. Likewise `DB_ENGINE`,
`DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` are used only when
`DATABASE_URL` is absent.

### Validation

Settings are validated at startup. Missing or malformed values raise
`ImproperlyConfigured` with a list of problems, for example:

```
Invalid configuration:
 - No forwarding destination configured. Add forward_to=... to MAILGEN_URL.
 - Address length must be an integer between 6 and 40.
```

Messages never include secrets. `DJANGO_SECRET_KEY` and `MAILGEN_FIELD_KEY` are separate
on purpose: rotating sessions must not make stored mailbox passwords unreadable, and vice
versa. A missing `MAILGEN_FIELD_KEY` is reported by `manage.py check` and the diagnostics
page (so `generate_field_key` remains usable on a fresh install); a malformed one is a
startup error.

## Local quick start

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env                 # fill in DATABASE_URL, MAILGEN_URL and the cPanel/IMAP values
python manage.py generate_field_key  # paste into MAILGEN_FIELD_KEY
python manage.py migrate
python manage.py create_admin --username admin
python manage.py collectstatic --noinput
python manage.py runserver
```

Open <http://127.0.0.1:8000/> and sign in.

## Static files and the Django admin

cPanel/Passenger does not serve `/static/` itself, so **WhiteNoise** serves both the app's
Bootstrap assets and Django's admin CSS/JS. Run `collectstatic` during deployment; after
that `/static/admin/css/base.css` is served by the app with `DEBUG=0`.

## Tests

```bash
python manage.py test
```

149 tests cover URL parsing and configuration validation, startup failure modes,
provisioning, IMAP adapter mapping, sync/idempotency, sanitisation, CSRF, login
throttling, host/referrer-policy regressions, lifecycle actions, diagnostics and the
admin static pipeline. They use fakes for cPanel and IMAP, so they run without hosting
access.

## Layout

```
manage.py, mailgen/        Django project (settings, urls, config parsing, wsgi)
generator/                 app: models, views, forms, services, admin, checks
  services/cpanel.py       cPanel UAPI client
  services/addresses.py    generation + provisioning + lifecycle
  services/imap.py         imap-tools adapter
  services/sync.py         incremental sync
  services/sanitizer.py    nh3 allow-list + sandboxed document
  services/diagnostics.py  read-only health checks
templates/, static/        Bootstrap 5 (vendored, no CDN)
docs/                      deployment, preflight, security, verification
legacy/php-mvp-v2/         archived PHP prototype (not used)
```

## Deployment

See [`docs/DEPLOYMENT-CPANEL.md`](docs/DEPLOYMENT-CPANEL.md) and run the checks in
[`docs/PREFLIGHT.md`](docs/PREFLIGHT.md) **before** pointing the app at real mailboxes.
