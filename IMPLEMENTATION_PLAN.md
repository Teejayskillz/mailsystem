# Personal Email Generator — MVP v2 (revised, smaller first release)

**Status:** plan only. No application code written.
**Supersedes:** the broader plan previously in this file. v2 deliberately cuts scope.

**Testing disclaimer:** I have **not** accessed your cPanel account or server. Nothing here is a test result for your hosting. Every host-dependent item is a check **you** run in Phase 0; the outcome decides whether we build.

---

## 0. What changed from v1, and why

| v1 | v2 | Reason |
|---|---|---|
| Custom IMAP client | Maintained library (`webklex/php-imap`) | MIME parsing is where custom code breaks; MIT, active, no `ext-imap` needed |
| OTP extraction + OTP column + TTL purge | **Removed.** Codes are read in the message body | Less parsing, less storage, no false "code" matches |
| Send / reply via SMTP in MVP | **Deferred** until receive+forward passes end-to-end | Sending depends on receiving being proven |
| Attachments (metadata + download) | **Deferred** | Not needed for the core workflow |
| Advanced search (FULLTEXT, filters) | **Deferred.** One address filter + one text box | Core workflow first |
| Full sanitized body stored in DB | **Not stored at all**; body fetched on open | Minimizes storage and exposure |
| 9 tables | 6 tables | Smaller surface |
| TOTP 2FA, expanded audit, outbox | Deferred / minimal | Personal single-user tool |
| Catch-all as fallback mode | **Not used**; default address untouched | Removes a domain-wide side effect |

Kept: PHP + MySQL, cPanel, single-admin login, random address generation, forwarding to your primary, dashboard inbox, per-address disable/delete, evidence-based status.

---

## 1. Address domain: main domain or dedicated email subdomain?

Decide this from Phase 0 results, not preference. Full comparison:

### 1.1 The two options

**Option A — addresses on your main domain** (`7k3m9q2x@example.com`)
- Ordinary cPanel mailboxes on `example.com`.
- Works only if `example.com` is a **mail domain on this account** and mail is **routed locally** (MX → this server). cPanel exposes the list via `Email::list_mail_domains` ([spec](https://api.docs.cpanel.net/specifications/cpanel.openapi/email-accounts/email-list_mail_domains.md)).
- No DNS change, no new certificate, no new MX.

**Option B — addresses on a dedicated email subdomain** (`7k3m9q2x@inbox.example.com`)
- A cPanel subdomain with an A record plus an **MX record for `inbox.example.com` pointing at this server**.
- Subdomain mail is independent of the parent domain's MX — so it still works if `example.com` mail is at Google/Microsoft. That is its main advantage.
- ⚠️ Whether cPanel adds the subdomain MX automatically is **unverified**; if DNS is external, you add it by hand and wait for propagation.
- ❓ Whether a new cPanel subdomain is immediately a local mail domain must be tested (Phase 0, check F).

### 1.2 Implications

| | A: main domain | B: dedicated subdomain |
|---|---|---|
| DNS work | none | A + MX record (manual if external DNS) |
| New failure mode | none | MX missing/mispointed ⇒ silent non-delivery |
| Isolation from real mail | shares namespace with real mailboxes | fully isolated |
| Collision with a real address | possible; mitigated by prefix + DB/server checks | effectively impossible |
| Mailbox/quota capacity | cPanel account limit | **same account limit** (no capacity gain) |
| Reset/experiment cost | touches the real domain | delete the subdomain to reset |
| If `example.com` mail is at Google | **does not work** | works (own MX) |
| Recipient-side validation | best | very good; a minority of signup forms handle multi-label domains poorly |
| Naming hazard | none | **avoid `mail.`** — cPanel reserves `cpanel`, `webmail`, `whm`, `webdisk`, `cpcalendars`, `cpcontacts`, `autoconfig`, `autodiscover` ([docs](https://docs.cpanel.net/knowledge-base/general-systems-administration/service-and-proxy-subdomains/)), and `mail.` is conventionally the MX host |

### 1.3 Recommendation

1. **Default for the MVP: Option A**, if Phase 0 shows `example.com` is a locally-routed mail domain. It removes an entire class of DNS/MX failures and changes nothing that already exists. Use a prefix (`otp-`, `signup-`) so generated names cannot collide with real people.
2. **Use Option B** if (a) `example.com` mail is hosted elsewhere, (b) you want generated addresses fully isolated from real mailboxes, or (c) you may later experiment with a catch-all on that subdomain without touching real mail.
3. Never reuse `mail.` or another cPanel service-subdomain name.
4. Neither option changes the **domain-wide default address**, and v2 does not touch catch-all at all.

**Decision needed:** A or B, after check D (is `example.com` mail local?).

---

## 2. Architecture (MVP)

```
Browser ──HTTPS──► app.example.com        docroot: /home/USER/mailapp/public
                     public/index.php      front controller, ~9 routes
                     app/  views/  vendor/  storage/
                     │
                     ├─ PDO ──────────► MySQL: cpuser_mailapp
                     ├─ HTTPS 2083 ───► cPanel UAPI (token) → Email::*
                     └─ IMAPS 993 ────► Dovecot, one login per address
                                        (webklex/php-imap, no ext-imap)
/home/USER/mailapp/config/config.php   ← 0600, ABOVE the docroot, never web-served
```

- One subdomain for the app (web only). Generated addresses live on the mail domain chosen in §1.
- **No sending path, no queue, no worker.** Sync runs inside a request (page load / refresh) and optionally a 5-minute cPanel cron hitting a CLI script.
- Mail flow: sender → MX → Exim → mailbox (local copy) + forwarder copy → your primary. The app proves inbox access by logging in to that mailbox over IMAP.

### 2.1 Routes (complete)

| Method | Path | Purpose |
|---|---|---|
| GET/POST | `/login` | sign in |
| POST | `/logout` | destroy session |
| GET | `/` | dashboard: addresses + recent messages |
| POST | `/addresses` | generate one address |
| POST | `/addresses/{id}/disable` \| `/enable` \| `/delete` | lifecycle |
| GET | `/addresses/{id}` | that address's inbox |
| POST | `/sync` | pull new mail (JSON) |
| GET | `/messages/{id}` | open one message (sanitized) |
| GET | `/diagnostics` | live hosting/health checks |

Everything except `/login` requires a session; every POST requires a CSRF token and is rejected on cross-origin.

### 2.2 Directory and secret placement

```
/home/USER/mailapp/
  config/config.php     0600  DB creds, APP_KEY, cPanel token, limits
  app/                  application code (not web-accessible)
  vendor/               committed dependencies (no Composer on the server)
  storage/              logs, sessions (0700, not web-accessible)
  public/               ← ONLY this is the subdomain docroot
```

Trust boundary: the web server reaches `public/` only. `config.php` is a sibling directory, never inside the docroot, so a PHP-handler misconfiguration cannot serve it and path traversal has one fewer target. `APP_KEY` lives there; mailbox passwords and the cPanel token are sealed with `sodium_crypto_secretbox` before touching MySQL.

---

## 3. IMAP library decision

**Chosen: `webklex/php-imap` v6.2.0** — MIT, ~10.1M installs, active, pure PHP over TLS sockets, no `ext-imap`.

| Fact | Detail |
|---|---|
| PHP | `^8.0.2` |
| Required extensions | `fileinfo`, `iconv`, `json`, `libxml`, `mbstring`, `openssl`, `zip` |
| Transitive deps | `illuminate/pagination`, `nesbot/carbon`, `symfony/http-foundation` |
| Deploy | `composer install` on your dev machine, commit `vendor/`, upload; **no Composer on the server** |
| Source | [packagist](https://packagist.org/packages/webklex/php-imap) |

**Why not a custom client:** the hard part is not the IMAP verbs, it is MIME — nested multipart, base64/quoted-printable, RFC 2047 headers, RFC 2231 filenames, broken charsets, `message/rfc822` parts, and malformed real-world mail. A hand-rolled parser is where an MVP quietly loses messages or renders the wrong body. This is the case where a maintained library wins on reliability per unit of effort.

**Why not `ext-imap`:** deprecated, absent by default on PHP 8.4+ ([cPanel docs](https://docs.cpanel.net/ea4/php/php-module-imap/)), host-dependent. The library can use it for better decoding but does not require it.

**Costs accepted:** a few MB of vendor code, three transitive packages, a dependency we do not control. Mitigations: pin the exact version, run `composer audit` before deploying, add a Phase 3 fixture test with real messages.

**Fallback if Phase 0 shows missing extensions:** `barbushin/php-imap` or `DirectoryTree/ImapEngine`. Never a custom parser.

---

## 4. Address lifecycle and the three evidence levels

Generation: CSPRNG local part (10–12 chars, look-alike-free alphabet, configurable prefix). Two-phase create — DB row `pending` (UNIQUE index is the collision gate) → `Email::add_pop` → `Email::add_forwarder` to your primary → **re-read** `list_pops` + `list_forwarders` to confirm. Failures become `failed` with an error plus retry/cleanup. Deleted addresses keep a tombstone and are never reissued.

| Level | Badge | Proof | Set by |
|---|---|---|---|
| 1 | **Configured** | mailbox and forwarder both observed in `list_pops` / `list_forwarders` | automatic |
| 2 | **Inbox-capable** | TLS IMAP `LOGIN` + `SELECT INBOX` succeeded | automatic |
| 3 | **Delivery-tested** | at least one message from an **external** sender was fetched from that mailbox | automatic on first external message |

A fourth fact is kept separately and is **user-asserted**: `forward_confirmed_at` — "I saw the forwarded copy in my primary inbox". It is never merged into "delivery-tested", and no screen claims guaranteed delivery.

Disable = `Email::delete_forwarder` + `Email::suspend_incoming` (mailbox kept, so catch-all can never take the address over). Enable reverses both. Delete = `delete_forwarder` + `delete_pop`. Each action re-reads server state and updates the badges.

---

## 5. Inbox behaviour

- **Sync:** for each active, inbox-capable address: connect, open INBOX, fetch messages with `UID > imap_last_uid`, store headers only, update `uidvalidity`/`last_uid`. Batched 3–5 addresses per request, 20 s time box, MySQL advisory lock so two tabs cannot double-fetch.
- **Stored:** sender, subject, date, size, flags/read state, `message_id`, UID. **Nothing else** — no body, no preview, no attachments, no OTP.
- **Message view:** fetch that one message by UID at open time; render text/plain escaped, HTML through an allowlist sanitizer inside a sandboxed iframe (`sandbox` without scripts, strict CSP, remote images blocked). If it is gone from IMAP, show a clear "no longer on the server" state.
- **Search:** one address dropdown + one text box matching `from_addr`/`subject` with `LIKE`. Not full-text, not body search.
- **Read state:** from IMAP flags during sync; opening a message may set `\Seen` (best effort, failure ignored).

---

## 6. Security (MVP-sized)

| Area | Control |
|---|---|
| Admin | single row, Argon2id (bcrypt fallback), no registration route, setup via CLI script |
| Sessions | `use_strict_mode`, 48-char id, regenerate on login, `Secure`/`HttpOnly`/`SameSite=Strict`, idle 30 min, absolute 12 h, `session_epoch` for "log out everywhere" |
| CSRF | per-session token, `hash_equals`, required on every POST, plus `Origin`/`Sec-Fetch-Site` check |
| Throttling (DB, no Redis) | login 5/15 min; generate 10/h; sync 30/min |
| SQL | PDO, emulation off, prepared statements, identifiers from a fixed allowlist |
| Secrets | `config.php` 0600 above docroot; token and mailbox passwords sealed with `sodium`; logs redact both |
| Output | escape by default; the only raw HTML is the sanitized message iframe |
| Headers | CSP `default-src 'self'`, `nosniff`, `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY` |
| Errors | `display_errors=Off`, log outside docroot, generic error page |

---

## 7. Database (6 tables)

| Table | Purpose | Key fields |
|---|---|---|
| `admin` | the single account | `username`, `password_hash`, `session_epoch`, `failed_count`, `locked_until`, `last_login_at` |
| `settings` | runtime config | `k`, `v` (`address_domain`, `address_prefix`, `forward_to`, `max_addresses`, `quota_mb`) |
| `addresses` | registry + server evidence | `address` UNIQUE, `local_part`, `domain`, `label`, `status`, `password_enc`, `quota_mb`, `forward_to`, `server_verified_at`, `imap_verified_at`, `first_external_mail_at`, `forward_confirmed_at`, `imap_uidvalidity`, `imap_last_uid`, `last_synced_at`, `last_error`, `deleted_at` |
| `messages` | thin index only | `address_id`, `uidvalidity`, `uid`, `message_id`, `from_addr`, `from_name`, `subject`, `sent_at`, `size_bytes`, `is_read`; UNIQUE(`address_id`,`uidvalidity`,`uid`) |
| `login_attempts` | login throttling + forensics | `ip`, `username`, `ok`, `created_at` |
| `throttle` | generic counters | `bucket`, `key_hash`, `window_start`, `counter` |

No OTP column, no body column, no attachments table, no outbox. Mail stays in the mailbox; the DB is an index.

---

## 8. Phase 0 — minimum hosting checks (run before any code)

I cannot run these. Each is executed by you (cPanel UI, `dig`, one `curl`, one throwaway mailbox). Record pass/fail; **any failure in B, C, D, E or F stops the build**.

| # | Area | Check | Pass criteria | If it fails |
|---|---|---|---|---|
| A | PHP compatibility | cPanel version; PHP versions in MultiPHP; `php -m` (or phpinfo) for `pdo_mysql, openssl, mbstring, curl, fileinfo, iconv, zip, libxml, json, sodium, dom` | PHP 8.1–8.3 selectable; all extensions present | Pin 8.2/8.3; ask host for missing extension; swap IMAP library |
| B | cPanel API access | Create token (Security → Manage API Tokens), then `curl -sS -H "Authorization: cpanel USER:TOKEN" "https://SERVER:2083/execute/Email/list_pops"` | HTTP 200 + JSON `result.status: 1` | Tokens disabled/blocked ⇒ no automatic provisioning; replan or stop |
| C | Mailbox limits | cPanel → Email Accounts shows used/limit; note max quota; create **one throwaway** mailbox the same way the app will, then delete it | Create + delete succeed; limit/quota recorded | Lower `MAX_ADDRESSES`; if no headroom, stop |
| D | MX routing | cPanel → Email Routing; `dig MX example.com`; `Email::list_mail_domains` | Domain listed as a mail domain; MX → this server; routing = Local | Option A invalid ⇒ use Option B or stop |
| E | Forwarding | On the throwaway mailbox add a forwarder to your primary; send a test from an external account (e.g. Gmail) | Primary receives it; `list_forwarders` shows the rule | Forwarding is the product; stop and investigate |
| F | IMAP access | Log in to the throwaway mailbox over IMAPS 993 (mail client or library test); list one message | TLS login OK; INBOX readable | Inbox is the product; stop and investigate |
| G | Deploy path | Confirm you can upload a `vendor/` directory (File Manager zip or Git Version Control) | Upload works; no server-side Composer | Use Git Version Control |
| H | Optional | Cron availability; disk headroom; who controls DNS | Recorded | Sync stays request-driven |

Note: a cPanel API token is full-account power and only exists if your host leaves *Manage API Tokens* enabled (Feature Manager).

---

## 9. Implementation sequence with acceptance criteria

### Phase 1 — Foundation and login
Config loader (outside docroot), PDO, front controller, error/log handling, security headers, single-admin login, sessions, CSRF, throttling, logout.
**Accept when:**
- Login works; wrong password 5× → throttled and locked.
- Any POST without a valid CSRF token → rejected, no state change.
- Session id changes on login; cookie has `Secure`, `HttpOnly`, `SameSite=Strict`.
- Requests to `/config.php`, `/app/*`, `/storage/*` → 404/403.
- No notices or stack traces reach the browser.

### Phase 2 — Address provisioning
Generate button, two-phase create via UAPI, re-read verification, list view (copy, badges, error text), disable/enable/delete.
**Accept when:**
- A generated address appears in cPanel → Email Accounts and in Forwarders, with **Configured** and **Inbox-capable**.
- Generating twice for the same local part never duplicates (DB constraint + server check).
- Disable → `suspend_incoming` true, forwarder gone, a new external mail is rejected, primary receives nothing.
- Enable → forwarder restored, mail flows again.
- Delete → mailbox and forwarder absent from cPanel; row tombstoned; never reissued.
- Every action re-reads server state rather than trusting the DB.

### Phase 3 — Inbox sync
Library integration, per-address connection, incremental UID fetch, batching, advisory lock, error states.
**Accept when:**
- An external message appears within one refresh.
- A second sync imports zero duplicates and only new UIDs.
- A malformed message does not break the loop (fixture test).
- IMAP down for one address → that address shows an error; others still work.
- Two concurrent syncs do not duplicate rows.

### Phase 4 — Message view
Per-message fetch by UID, sanitizer, sandboxed iframe, plain-text rendering, read state.
**Accept when:**
- HTML mail renders without scripts: `onerror`, `javascript:`, iframes, forms and remote images are neutralised/blocked.
- Plain-text mail cannot inject HTML.
- A code in the body is simply readable text — no extraction, no storage.
- A message deleted from the mailbox shows a clear "not on server" state.

### Phase 5 — Hardening and acceptance
Diagnostics page, minimal audit log, setup docs, backup/rollback notes.
**Accept when:** §10 passes in full, over HTTPS, with `display_errors` off.

---

## 10. End-to-end acceptance test (the one that matters)

1. Log in over HTTPS.
2. Generate one address; see **Configured** and **Inbox-capable**.
3. From an external account, send a message containing a visible code to that address.
4. Refresh: message appears; badge becomes **Delivery-tested**; you confirm the forwarded copy in your primary inbox.
5. Open the message: code readable, HTML safe, no tracking image loaded.
6. Disable; send again from outside → rejected at SMTP, nothing in your primary.
7. Enable; send again → arrives again.
8. Delete; the address is gone from cPanel.
9. Log out; the session is invalid on re-use.
10. Confirm the domain's default address and Email Routing are unchanged.

---

## 11. Explicitly out of scope (v2)

Sending and replying · attachments · OTP extraction/storage · catch-all automation · IMAP flag write-back beyond best-effort `\Seen` · full-text/body search · labels/export · 2FA · multi-user · API · mobile app · background worker · automatic mailbox pruning · HTML compose.

Each is a Phase 6+ candidate **after** §10 passes.

---

## 12. Open decisions (needed before Phase 1)

1. **Domain option A or B** — depends on check D.
2. **Primary address** to forward to (and whether it is on this server).
3. **API token** — can you create one? (check B)
4. **Mailbox headroom** — how many accounts does the package allow? (check C)
5. **cPanel + PHP versions**; can you select 8.2/8.3 per subdomain? (check A)
6. **Deploy method** — File Manager zip or cPanel Git Version Control? (check G)
7. **App subdomain name** — e.g. `app.example.com`; must not be `mail.`, `webmail`, `cpanel`, `autodiscover`, `autoconfig`, `cpcalendars`, `cpcontacts`.
8. **Defaults** — max addresses (suggest 10 for the first release), per-mailbox quota (suggest 100 MB), address prefix (suggest `otp-`).

---

## 13. Residual risks

| Risk | Mitigation |
|---|---|
| MX/routing not local (check D) | Stop before coding; use Option B |
| API tokens disabled by host | Stop, or manual mode (out of v2 scope) |
| No mailbox headroom | Cap addresses low; show remaining at generate time |
| Library incompatible with host extensions | Phase 0 check A; swap to `barbushin/php-imap` |
| Forwarded copies land in spam at the primary | Phase 0 check E; advisory only, never guaranteed |
| Deleted address falls through to the domain's existing default address | Documented; "disable" avoids it by keeping the mailbox |
| Token compromise = full cPanel account | Config above docroot, encrypted, no uploads, strict CSP, rotation runbook |
