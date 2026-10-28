# Deploying to cPanel (Passenger / "Setup Python App")

This mirrors the deployment pattern already used by your other cPanel Django projects
(`passenger_wsgi.py` + virtualenv + PyMySQL + WhiteNoise), updated to Django 5.2.

> No production resources are touched by this repository. Every step below is run by you.

## 1. Create the subdomain

cPanel » **Domains** → create `app.example.com` (or similar).

- Note its **document root** — this will be the application root.
- Do **not** reuse `mail.`, `webmail.`, `cpanel`, `autodiscover`, `autoconfig`,
  `cpcalendars` or `cpcontacts`: those are cPanel service names.
- Run AutoSSL for the subdomain and confirm HTTPS before continuing.

## 2. Create the Python application

cPanel » **Setup Python App** → *Create application*:

| Field | Value |
|-------|-------|
| Python version | 3.11 or 3.12 (3.10 minimum) |
| Application root | the subdomain root, e.g. `apps/mailgen` |
| Application URL | `app.example.com` |
| Application startup file | `passenger_wsgi.py` |

cPanel creates a virtualenv under `/home/USER/virtualenv/app.example.com/<version>/`.

## 3. Upload the code

Use cPanel **Git Version Control** (recommended) or upload a zip via File Manager, into the
application root. The root must contain `manage.py` and `passenger_wsgi.py`.

Do **not** upload `.env` with real secrets into the web root.

## 4. Install dependencies

From cPanel's terminal (or the "Run pip install" box):

```bash
source /home/USER/virtualenv/app.example.com/3.11/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## 5. Secrets outside the document root

```bash
mkdir -p /home/USER/.mailgen
cp .env.example /home/USER/.mailgen/env
chmod 600 /home/USER/.mailgen/env
# edit /home/USER/.mailgen/env with real values
python manage.py generate_field_key   # paste into MAILGEN_FIELD_KEY
```

Only these values are required:

```
DJANGO_SECRET_KEY=...
DATABASE_URL=mysql://cpuser_mailgen:PASSWORD@localhost:3306/cpuser_mailgen?charset=utf8mb4
MAILGEN_URL=mailgen://example.com?prefix=otp-&length=10&forward_to=primary@example.com&max_addresses=10&quota_mb=100
MAILGEN_FIELD_KEY=...
CPANEL_BASE_URL=https://server.example.com:2083
CPANEL_USER=cpuser
CPANEL_TOKEN=...
IMAP_HOST=mail.example.com
```

`passenger_wsgi.py` defaults `MAILGEN_ENV_FILE` to `/home/USER/.mailgen/env`; adjust the
path there if you use a different location. The file is outside the document root and is
never served. Credentials stay in their own variables — never inside `MAILGEN_URL`.

## 6. Database

cPanel » **MySQL Databases**: create `cpuser_mailgen` and a user with privileges on that
database only. Put the credentials in `DATABASE_URL` (percent-encode special characters,
e.g. `p@ss` → `p%40ss`).

## 7. Initialise

```bash
source /home/USER/virtualenv/app.example.com/3.11/bin/activate
cd /home/USER/apps/mailgen

python manage.py check                 # configuration validation
python manage.py migrate
python manage.py collectstatic --noinput   # required for admin CSS/JS (WhiteNoise)
python manage.py create_admin --username admin     # prompts for a password
python manage.py check_hosting --offline
```

Restart the application from cPanel » Setup Python App.

## 8. First login and real checks

1. Open `https://app.example.com/` and sign in.
2. **Diagnostics → Run live checks.** Fix any FAIL before creating addresses.
3. Create one address, then:
   - confirm it appears in cPanel » Email Accounts and Forwarders;
   - send a real message from an external account to it;
   - press **Sync inboxes** and confirm the message appears;
   - confirm the forwarded copy in your primary inbox, then press
     **"I saw the forwarded copy"**.

## 9. Scheduled sync (optional)

cPanel » **Cron Jobs**, every 5 minutes:

```
/home/USER/virtualenv/app.example.com/3.11/bin/python /home/USER/apps/mailgen/manage.py sync_mail
```

Use the absolute interpreter path; Passenger apps do not have the venv activated for cron.

## 10. HSTS (only after HTTPS is confirmed)

Set `DJANGO_HSTS_SECONDS=31536000` in the env file and restart. Do not enable HSTS while
still testing on HTTP.

## Rollback

1. cPanel » Setup Python App → **Stop / Destroy** the application.
2. Remove the subdomain (this does not touch other sites).
3. The database is untouched until you explicitly drop it.

Nothing here modifies other websites, MX records, Email Routing or the domain default
address.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| 500 with "DJANGO_SECRET_KEY is required" | env file not found; check `MAILGEN_ENV_FILE` |
| Login page loads, static files 404 | `collectstatic` not run / wrong app root |
| `ImproperlyConfigured: PyMySQL` | requirements not installed in the app's venv |
| Diagnostics: cPanel 401/403 | token revoked, wrong account name, or Feature Manager disabled |
| `cPanel API error … unknown error` (older builds) | an earlier client build read only the wrapped UAPI envelope (`{"result":{…}}`). Some cPanel hosts return a **flat** envelope (`{"status":1,"data":…}`). The client now accepts both; if a `status: 0` arrives with no text, the message names the Email module / *Receive Mail* role instead of "unknown error". |
| Diagnostics: cPanel request failed | outbound 2083 blocked from the server |
| IMAP login failed | wrong host/port, certificate mismatch, mailbox password rotated |
| `DisallowedHost` with a backslash, e.g. `'www\.example\.com'` | the URL, vhost or proxy escaped the dots. The app strips illegal backslashes from the Host header (still validated against `ALLOWED_HOSTS`) and logs `host header contained backslashes`. Also fix the source: the cPanel application URL / vhost `ServerName` and any bookmark should be the plain hostname. |
| 403 “Origin checking failed - null” on `/login/` or `/admin/login/` | **root cause:** a `Referrer-Policy: no-referrer` response makes browsers serialise the Origin of a same-origin form POST as `null`. The app now sends `same-origin` on HTML pages, which fixes it. If it ever recurs, check for a proxy/vhost that injects `no-referrer`, and for preview panes or sandboxed iframes. The app never trusts `null`; `csrf_failure` logs host/origin/referer/Sec-Fetch/referrer-policy. |
| 403 “Origin checking failed - https://… does not match any trusted origins” | the origin is legitimate but not trusted. `CSRF_TRUSTED_ORIGINS` hard-codes both HTTPS hosts; if you move to another domain, update the constants in `mailgen/settings.py`. |
