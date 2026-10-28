# Security notes

## Assets to protect

| Asset | Where it lives | Protection |
|---|---|---|
| Django `SECRET_KEY` | env file outside docroot, mode 600 | never logged, never rendered |
| `MAILGEN_FIELD_KEY` | env file outside docroot | encrypts mailbox passwords (Fernet) |
| Database password | inside `DATABASE_URL`, env file outside docroot | mode 600; never rendered or logged |
| cPanel API token | env file outside docroot | full account power; rotate if leaked |
| Mailbox passwords | MySQL, Fernet ciphertext only | decrypted in memory for IMAP |
| Session data | MySQL `django_session` | HttpOnly, Secure, SameSite=Strict |
| Message bodies | **not stored** | fetched from IMAP when opened |

`DJANGO_SECRET_KEY` (session/CSRF signing) and `MAILGEN_FIELD_KEY` (mailbox-password
encryption) are deliberately separate: rotating one must not invalidate the other.
`MAILGEN_URL` carries only address policy — the parser rejects URLs containing
credentials, so cPanel and database secrets cannot drift into it.

Startup validation reports missing or malformed values by *name* only; it never echoes the
value, so a misconfiguration cannot leak a secret into a log or an error page.

If the field key is rotated, stored mailbox passwords become unreadable. The app reports
this instead of crashing silently; re-create the affected addresses.

If the cPanel token leaks: revoke it in cPanel » Manage API Tokens, create a new one, update
the env file, restart the app.

## Controls in place

- **Authentication** – Django auth with Argon2/PBKDF2 hashing; only `is_staff` users can
  log in; no registration route exists.
- **Login throttling** – 5 attempts per IP+username per 15 minutes, plus a wider IP limit.
  Counters live in MySQL (Django's locmem cache is per-process on Passenger).
- **Sessions** – database sessions, 12 h absolute lifetime, 30 min idle timeout enforced by
  middleware, rotated on login, `Secure`/`HttpOnly`/`SameSite=Strict` outside DEBUG.
- **CSRF** – Django's middleware on every state-changing view; only POST mutates state.
  `CSRF_TRUSTED_ORIGINS` is a hard-coded list of the two HTTPS hosts; `Origin: null` is
  never trusted. Rejected requests are logged with host/origin/referer/Sec-Fetch metadata
  (never cookies or tokens) to make client-side causes diagnosable.
- **Host header** – `ALLOWED_HOSTS` is hard-coded for this deployment (plus normalised
  environment extras and localhost when `DEBUG=1`). A middleware strips illegal
  backslashes from `Host` before validation; because Django still checks the cleaned value
  against `ALLOWED_HOSTS`, this cannot be used to bypass host validation.
- **Authorisation** – every view except `/login/` is `@login_required`.
- **SQL** – Django ORM only; no raw SQL or string-built queries.
- **XSS** – email HTML is rebuilt by `nh3` against an allow-list (no scripts, no styles, no
  images, no forms, no iframes), then served from `/messages/<id>/render/` inside an iframe
  with `sandbox` and a `default-src 'none'` CSP. Two independent layers.
- **Remote images** – removed entirely; no tracking pixels are fetched.
- **Headers** – CSP (self-only), `X-Frame-Options: DENY` on app pages (SAMEORIGIN for the
  message frame), `Referrer-Policy: same-origin` on HTML pages, `nosniff`, `Permissions-Policy`,
  `Cross-Origin-Opener-Policy`.
- **Errors** – `DEBUG=0` in production; custom 404/500 pages; stack traces go to
  `logs/app.log` only.
- **Referrer policy** – HTML pages use `same-origin`, never `no-referrer`. Per the Fetch
  standard a `no-referrer` policy makes browsers send `Origin: null` on same-origin form
  POSTs, which Django's CSRF origin check correctly rejects. The sandboxed message document
  (no forms, its own CSP) keeps `no-referrer`.
- **Logging** – no tokens, passwords or message bodies; login events record IP + username.

## Threat notes

- **The API token is the account.** A compromise of this app is a compromise of the cPanel
  account. Keep the app on its own subdomain, keep the env file outside the docroot, and
  keep `/admin/` limited to the single superuser.
- **Django admin** is enabled for convenience. If you do not need it, remove the
  `path("admin/", ...)` route and the `django.contrib.admin` app.
- **Deleted addresses** keep a tombstone row so the same local part is never reissued. The
  mailbox itself is removed from cPanel, so mail to it falls through to whatever your
  domain's *existing* default-address behaviour is. That is why "disable" is the safer
  operation: it keeps the mailbox and suspends inbound delivery.
- **Mailbox quotas** are set per address (`MAILGEN_QUOTA_MB`). The app does not prune IMAP
  mail; use the mailbox quota and delete stale addresses.
- **No sending path exists**, so there is no spam/relay risk from this app.

## Deployment checklist

- [ ] `DJANGO_DEBUG=0`
- [ ] `DJANGO_SECRET_KEY` random, >= 50 chars
- [ ] env file outside the document root, mode 600
- [ ] `DJANGO_ALLOWED_HOSTS` and `DJANGO_CSRF_TRUSTED_ORIGINS` set to the real host
- [ ] HTTPS enforced; HSTS enabled after verification
- [ ] `python manage.py check --deploy` reviewed
- [ ] `collectstatic` run
- [ ] admin password stored in a password manager
- [ ] API token and field key backed up securely
