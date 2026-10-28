# Hosting preflight (run before trusting the app)

Nothing in this file has been executed against your cPanel account. These are the checks
**you** run. Do not paste API tokens or passwords into chat; keep them in the env file.

Record the result of each check. Any failure in **C, D, E, F or G** means the dependent
feature must stay disabled until it is fixed — do not "work around" it by changing the
architecture.

| # | Area | How to check | Pass criteria |
|---|------|--------------|---------------|
| A | Python / Django support | cPanel » **Setup Python App** (or your host's equivalent) | Python 3.10+ selectable; an app can be created for the subdomain |
| B | Database | cPanel » MySQL Databases: create DB + user, attach user with ALL on that DB | Connection succeeds (`python manage.py migrate`) |
| C | cPanel UAPI token | cPanel » Security » **Manage API Tokens** → create token for your account | Feature visible and a token can be created |
| D | Token actually works | From the server (SSH/Terminal) or via `python manage.py check_hosting`: `curl -sS -H "Authorization: cpanel USER:TOKEN" "https://SERVER:2083/execute/Email/list_mail_domains"` | HTTP 200, JSON with `"status":1` and your domain listed |
| E | Mail domain + MX | cPanel » **Email Routing**: the domain must be a *Local Mail Exchanger*; `dig MX example.com` | MX points at this server |
| F | Mailbox creation + limits | cPanel » **Email Accounts**: note used/limit. Create one throwaway mailbox the same way the app does, then delete it | Creation succeeds; limit and quota recorded |
| G | Forwarding | On the throwaway mailbox add a forwarder to your primary; send a test from Gmail | Primary inbox receives it |
| H | IMAP | Log in to the throwaway mailbox over IMAPS 993 with a mail client (or `manage.py check_hosting`) | TLS login + INBOX readable |
| I | Outbound from the app | After deployment, run `python manage.py check_hosting` | cPanel + DNS + IMAP checks pass |
| J | Disk headroom | cPanel » Disk Usage | Room for `staticfiles/`, logs and Django sessions |

## Important constraints (do not change these)

- **Do not** change the domain-wide **Default Address** / catch-all.
- **Do not** switch **Email Routing** from local to remote (or vice versa) to "make it work".
- **Do not** enable catch-all: disabled addresses rely on `suspend_incoming`, not on
  fall-through routing.

## cPanel API notes

- The token is **full-account power**; treat it like the cPanel password.
- Tokens can be disabled by the host in *Feature Manager*. If the menu is missing, the
  app cannot provision addresses.
- The app calls `https://<host>:2083/execute/Email/...` from the same server. Outbound
  loopback to that port must be allowed; a firewall rejection shows up as a FAIL in
  Diagnostics.

## IMAP notes

- Use the server hostname that has a valid TLS certificate (usually `mail.<domain>` or the
  cPanel server hostname), not `localhost` — unless your host's certificate covers it.
- `IMAP_VALIDATE_CERT=0` exists only for self-signed test setups; it disables TLS
  verification and should stay `1` in production.

## What "verified" will mean afterwards

1. `Configured` – the mailbox and forwarder are visible in cPanel after creation.
2. `Inbox-capable` – an IMAP login + `SELECT INBOX` succeeded.
3. `Delivery-tested` – a message from an external sender was fetched from that mailbox.

Only #3, plus a manual look at your primary inbox, is evidence that forwarding works.
