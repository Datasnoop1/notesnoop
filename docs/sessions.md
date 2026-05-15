# Sessions & Traction Analytics — GDPR Notes

DataSnoop runs a thin session-tracking layer to power the admin
**Traction** dashboard (session duration, pages-per-session, bounce
rate, retention cohorts). This doc explains exactly what we collect,
where it lives, how long we keep it, and why it's GDPR-compliant.

If a Belgian DPA inquiry lands or a user files an Article-15 request,
this doc is the paper trail.

---

## What we collect

| Artefact | Stored where | Stored how |
|---|---|---|
| `ds_sid` cookie | Browser only | Random UUIDv4 (`hex(16) bytes`). HttpOnly. SameSite=Lax. Secure on HTTPS. Path=/. Max-Age 30 days. |
| `activity_log.session_id` | Postgres | The same UUID, joined to a request row to derive session metrics. |
| `activity_log.ua_family` | Postgres | One of: `chrome`, `firefox`, `safari`, `edge`, `opera`, `bot`, `other`, `unknown`. **Bucketed at insert time — the raw User-Agent is never stored.** |
| `activity_log.device_type` | Postgres | One of: `desktop`, `mobile`, `tablet`, `bot`, `unknown`. |
| `activity_log.country_code` | Postgres | Two-letter ISO from Cloudflare's `CF-IPCountry` header, or NULL. |
| `activity_log.user_email` | Postgres | Email for authenticated users; for anonymous: `anon:<16-hex>` salted SHA-256 of the IP. **Raw IPs are never stored.** |
| `activity_log.request_origin` | Postgres | Coarse source for backend API calls: `direct`, `next-ssr`, `sitemap`, or `internal`. Used to keep Next.js render/prefetch noise out of scraper interpretation. |
| `activity_log.public_path` | Postgres | Public page path that caused an internal server-side fetch, when known, e.g. `/company/0400123456`. |
| `activity_log.bot_family` | Postgres | Coarse bot label derived from the request user-agent, e.g. `googlebot`, `gptbot`, or `declared_bot`. Raw User-Agent is still not stored. |
| `public_request_audit` | Postgres | Optional offline nginx-log ingest for public request evidence. Stores hashed client ID, sanitized route path without query strings, route kind, CBE, response size, same-site referrer path without query strings, bot/client type, and timestamps. |

**What we do _not_ collect:**

- Raw IP addresses (we hash with `ACTIVITY_LOG_IP_SALT`)
- Raw User-Agent strings (we bucket into 7 families)
- Raw nginx User-Agent strings, raw public IPs, or URL query strings in
  `public_request_audit`
- Canvas, font, WebGL, screen-size, hardware-concurrency, or any
  other browser-fingerprinting signal
- Cross-site referrer chains
- Mouse / keyboard / scroll events
- Form inputs (apart from the request URL itself, which is logged
  for `/api/*` calls)

The session-id cookie carries **zero PII** in itself. It is a random
opaque identifier that lets us correlate hits made by the same
browser. Joined with the (hashed) user identifier, it lets the admin
panel compute "average session duration" without ever knowing _who_
was in that session.

### Public request audit ingest

`activity_log` records backend API calls. Company pages are rendered by
Next.js, so a public `/company/...` request can create internal
`/api/companies/...` rows that otherwise look like anonymous guest
traffic. For scraper investigations, ingest nginx access logs into
`public_request_audit` instead:

```
ACTIVITY_LOG_IP_SALT=<same value as backend> \
DATABASE_URL=<prod database url> \
python scripts/ingest_public_request_audit.py --source docker --since 24h --verify-bots
```

The ingest is offline and idempotent (`event_hash` is unique), so it can
run from cron without touching the request path.

### Trust boundary on `CF-IPCountry`

The `country_code` column is populated from the `CF-IPCountry` request
header, which Cloudflare sets on every edge request. **If a request
ever reaches the origin without going through Cloudflare** (e.g. a
direct hit to `:8000` on the host network, or staging port 8080) a
hostile client can spoof this header. The blast radius is analytics
noise only — it cannot bypass auth or escalate privilege — but
operators reading the country mix should remember this. Hardening
option: strip `CF-IPCountry` at nginx and re-add only when
`CF-Connecting-IP` is in a Cloudflare-published source range.

### Cookie scope: host-only by design

`ds_sid` is set without a `Domain` attribute, so it is host-only. That
means `staging.datasnoop.be` and `datasnoop.be` keep separate sessions.
We don't merge staging analytics into prod, so the split is desirable.

---

## Cookie attributes

```
Set-Cookie: ds_sid=<uuid>; Max-Age=2592000; Path=/; HttpOnly;
            SameSite=Lax; Secure
```

* **HttpOnly** — JavaScript cannot read the cookie. Defends against
  XSS exfiltration.
* **SameSite=Lax** — never sent on cross-site sub-requests; required
  by Supabase OAuth callbacks.
* **Secure** — set only on HTTPS. The `SessionMiddleware` reads
  `X-Forwarded-Proto` (nginx terminates TLS in front of uvicorn) so
  staging on plain HTTP still gets a working cookie.
* **Max-Age 30 days** — hard ceiling. Idle browser tabs older than
  this re-mint a new session id on next request, which counts as a
  "new" session in analytics.

---

## Lawful basis

Under the GDPR, processing requires a lawful basis (Art. 6).

* **For authenticated users**: legitimate interest (Art. 6(1)(f)) —
  basic platform analytics that are necessary for operating the
  product. The user has signed up to a Belgian intelligence platform
  and consented to the Terms.
* **For anonymous visitors**: legitimate interest under Art. 6(1)(f),
  pursued only via the strictly-necessary cookie (`ds_sid`) and the
  hashed identifier. No marketing cookies, no third-party analytics
  trackers, no profiling for advertising.

The cookie is treated as **strictly necessary** under the ePrivacy
Directive (which the Belgian implementation transposed via Art. XII.95
of the Code of Economic Law) because it does not enable any function
the user did not request, and is purely first-party.

---

## Retention

* `activity_log` rows live forever today — we have not yet implemented
  a TTL sweep. **Action**: add a cron that drops rows where
  `created_at < NOW() - INTERVAL '90 days'`. Open as backlog item.
* The `ds_sid` cookie itself rotates after 30 days idle.
* On account deletion, the user's `user_email` rows in `activity_log`
  are nullable / can be deleted — we have not wired the user-delete
  flow into a cascading row delete yet. **Action**: add the cascade
  in the user-deletion endpoint.

---

## What the admin dashboard sees

The Traction tab calls these endpoints (all admin-only):

* `GET /api/admin/analytics` — aggregated metrics: visitors,
  registered users, sessions, daily trend, hourly heatmap, top pages,
  retention cohorts, dormant accounts, signups. **Admin traffic is
  excluded from every aggregation.**
* `GET /api/admin/sessions/breakdown` — device / browser / country
  mix from the bucketed columns.
* `GET /api/admin/sessions/paths` — top "page X → page Y" transitions
  per session.

* The Traction tab also reads `public_request_audit` when populated by
  `scripts/ingest_public_request_audit.py`, separating verified search bots,
  AI crawlers, normal browser prefetches, and high-signal extraction candidates.

All routes are gated by `_require_admin` (router-level dependency
checking the user's `user_roles.role = 'admin'`).

---

## DPO / Article-15 (subject access) request flow

When a user requests "all data we hold on me":

1. Look up `user_roles` rows by email.
2. Look up `activity_log` rows where `user_email = <email>`.
3. Anonymous activity tagged with the user's IP cannot be re-linked
   without the salt — and we never store the raw IP that produced the
   hash. Consider the anon rows out-of-scope for the Article-15 reply.
4. Look up `feedback`, `favourite`, `subscription_plan`, etc. as
   normal.

For an erasure request (Art. 17), the relevant rows are
`user_roles`, `feedback`, `favourite`, `subscription_plan`, plus
nulling `activity_log.user_email` for that email.

---

## Implementation pointers

| Concern | Code |
|---|---|
| Cookie set / read | `backend/main.py::SessionMiddleware` |
| Activity log writer | `backend/main.py::ActivityLogMiddleware` |
| UA bucket function | `backend/main.py::_ua_family` / `_device_type` |
| Schema columns | `backend/db.py::ensure_trgm_setup` (idempotent ALTER) |
| Admin analytics | `backend/routers/admin_phase22.py` |
| Frontend dashboards | `frontend/src/components/admin/traction-deep.tsx` |

---

## Changes to this doc

* 2026-04-26 — initial doc for Phase-22 admin rebuild.
