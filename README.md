# Personal Email Generator (Django MVP v2)

A private, single-administrator tool for generating throwaway addresses on **your own**
cPanel domain. Each address is a **real cPanel mailbox** with a **real forwarder** to your
primary inbox, and the dashboard reads it over IMAP.

> Status: Django rewrite of the earlier PHP prototype. See
> [`docs/VERIFICATION.md`](docs/VERIFICATION.md) for exactly what has been tested and what
> still requires your hosting.

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

## Local quick start

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env                 # then edit values
python manage.py generate_field_key  # paste into MAILGEN_FIELD_KEY
python manage.py migrate
python manage.py create_admin --username admin
python manage.py runserver
```

Open <http://127.0.0.1:8000/> and sign in.

## Tests

```bash
python manage.py test
```

61 tests cover provisioning, IMAP adapter mapping, sync/idempotency, sanitisation,
CSRF, login throttling, lifecycle actions and diagnostics. They use fakes for cPanel and
IMAP, so they run without any hosting access.

## Layout

```
manage.py, mailgen/        Django project (settings, urls, wsgi)
generator/                 app: models, views, forms, services, admin
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
