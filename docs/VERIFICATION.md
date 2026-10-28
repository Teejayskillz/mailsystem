# Verification record

Last run: local development environment (Windows, Python 3.12.14, Django 5.2.18,
MariaDB 10.11.10). **Your cPanel server was not accessed.** Nothing below proves that your
hosting works; it proves the code behaves correctly against controlled substitutes.

## Verified here (executed)

| Area | Evidence | Result |
|---|---|---|
| Django project boots | `manage.py check` | 0 issues |
| Migrations on MySQL/MariaDB | `manage.py migrate` | all applied (auth, admin, sessions, generator) |
| Test suite | `manage.py test` | **149 tests, OK** |
| `DATABASE_URL` parsing | mysql / mariadb / sqlite, percent-encoded credentials, default port, rejected schemes and parameters | pass |
| `MAILGEN_URL` parsing | domain from host or parameter, defaults, precedence of legacy variables, rejected credentials/paths/duplicates/unknown parameters | pass |
| Startup validation | missing/malformed values raise `ImproperlyConfigured` with a list; messages contain no secrets | pass (verified by subprocess run) |
| Production security defaults | `DEBUG=0` ⇒ Secure session/CSRF cookies, HTTPS redirect on | pass |
| Admin static files | WhiteNoise middleware order, storage backend, admin CSS discoverable and collected | pass |
| Admin CSS served with `DEBUG=0` | live server: `/static/admin/css/base.css` 200 `text/css` (22 KB), admin JS and Bootstrap also 200 | pass |
| Address generation | 50 samples, uniqueness + alphabet + prefix | pass |
| Provisioning happy path | fake cPanel: mailbox + forwarder + encrypted password | pass |
| Provisioning rollback | forwarder failure ⇒ mailbox deleted, status `failed` | pass |
| Domain not a mail domain | raises `ProvisioningError`, no rows written | pass |
| Address limit | enforced before any cPanel call | pass |
| Disable / enable / delete | server-state re-read, forwarder removal, `suspend_incoming` | pass |
| IMAP adapter mapping | mocked `imap-tools` boundary: login, UID range, UIDVALIDITY reset, envelope fields, body fetch | pass |
| Incremental sync | first import, second run 0 duplicates, UID high-water mark | pass |
| Evidence levels | `first_external_mail_at` only for external senders | pass |
| HTML sanitisation | scripts, handlers, `javascript:`, images, iframes, forms, styles removed; formatting kept | pass |
| Message rendering | CSP `sandbox`, `X-Frame-Options: SAMEORIGIN`, script-free body | pass |
| CSRF | POST without token ⇒ 403; with token ⇒ 302 | pass |
| CSRF origins (production fix) | POST `/login/` with `Origin: https://mailsystem.nzdworld.com` ⇒ 302; `Origin: null` ⇒ 403; foreign origin ⇒ 403; `/admin/login/` accepted | pass (live server + tests) |
| Referrer policy / `Origin: null` fix | `/login/`, `/admin/login/`, dashboard, diagnostics, 404 and CSRF-failure pages send `Referrer-Policy: same-origin` (not `no-referrer`); message render keeps `no-referrer` | pass (live server + tests) |
| Host header with backslashes | `Host: www\.mailsystem\.nzdworld\.com` ⇒ 200 on `/login/` and `/admin/login/`; foreign host still 400 | pass (live server + tests) |
| Host/origin normalisation | backslashes, quotes, case, trailing slash and duplicates removed; invalid entries rejected (strict) or dropped (lenient) | pass |
| Login throttling | 6th failed attempt returns 429 | pass |
| Non-staff login | rejected with generic message | pass |
| Logout | GET 405, POST destroys session | pass |
| Diagnostics | offline checks, no token leakage | pass |
| cPanel client over real HTTP | local mock UAPI: auth header, JSON parsing, 401 handling, create/disable/enable/delete | pass (14 assertions) |
| HTTP smoke test | live dev server: login, CSRF, dashboard, CSP header, static files, 404, anonymous redirect | pass (13 assertions) |

## Verified by framework (not app-specific testing needed)

Django's own test suite covers password hashing, session backends, CSRF internals, ORM
parameterisation and the admin. Version pinned: Django 5.2.18 (LTS, supported to April 2028).

## NOT verified — requires your hosting

| Item | Why it is unverified | How to verify |
|---|---|---|
| cPanel API token validity | no token exists here | `manage.py check_hosting` (live) |
| `add_pop` / `add_forwarder` on your server | mock only | create one address, then look in cPanel |
| Mailbox/package limits | unknown | cPanel » Email Accounts usage; generation is capped by `MAILGEN_MAX_ADDRESSES` |
| MX routing / local delivery | unknown | `dig MX`, cPanel » Email Routing |
| Real forwarding to your primary inbox | no primary mailbox here | send from Gmail; check the primary inbox |
| Real IMAP login to Dovecot | no mail server here | Diagnostics live check, or a throwaway mailbox |
| Incremental sync against a real mailbox | mocked transport | send two messages, sync twice, confirm no duplicates |
| HTML rendering of real-world email | only synthetic HTML | open a real newsletter/OTP message |
| cPanel Python app / Passenger deployment | not deployed | follow `docs/DEPLOYMENT-CPANEL.md` |
| Static files under WhiteNoise in production | dev server only | `collectstatic`, then load the login page |
| Docker/Node/Redis | not used anywhere | — |

## How to reproduce the local verification

```bash
python manage.py test
python manage.py check_hosting --offline
python manage.py runserver
```

The two integration harnesses used during development (mock cPanel UAPI server and the HTTP
smoke script) live under `.scratch/` and are not part of the deployable application.

## Honest statement

No address has been proven to receive mail, forward mail, or be readable over IMAP on your
account. The application is built so that it **reports** those facts only after observing
them, and refuses to label an address as working on the basis of a database row.
