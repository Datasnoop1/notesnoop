# Person v1 — Policy Decision Record

Status: **STUB — fill in before public Person URL ramp-up.**

The architecture deep-dive (`docs/data-architecture-deep-dive.html`,
"Three hard prerequisites for a public `/person/<id>` URL") makes
this record one of the three gates blocking the public URL. Until
every section below has a written decision (not a placeholder), the
`PERSON_PUBLIC_URL_ENABLED` feature flag stays OFF and the only
Person surface is the admin-gated audit view.

The reviewer (Belgian privacy lawyer) needs each section answered to
sign the legal memo. The operator approves before the flag flips.

---

## 1. Anonymous access

Decision: ☐ allowed / ☐ authenticated-only / ☐ tier-gated (specify tier)

Rationale: <fill in — KBO direct-marketing prohibition, GDPR
data-aggregation principles, competitor-positioning vs. Belfirst /
Companyweb / Graydon all bear here.>

If allowed: must be paired with hard rate-limit decisions in §2.

## 2. Rate limits — per-IP and per-account

Decision:

- Anonymous reads (if §1 allows): <X> req / min / IP, hard cap
  <Y> per IP per day.
- Authenticated free-tier: <X> req / min / account, hard cap
  <Y> per day.
- Paid tiers: <X> req / min / account, hard cap <Y> per day.

Mechanism: enforced at `backend/main.py` TierLimitMiddleware
classifier — add `/api/people/*` to the rate-counting endpoint
list, distinct bucket from `/api/companies/*`.

Backstop: nginx `limit_req` zone at the edge as defence-in-depth.

## 3. Robots / noindex / sitemap

Decision:

- `robots.txt` policy for `/person/*`: ☐ allow / ☐ disallow
- Meta `<meta name="robots" content="...">` on the page: <fill in>
- Sitemap: ☐ include / ☐ exclude

If disallowed in robots: still ship the rate limits in §2 — robots
is a hint, not enforcement, and ill-behaved scrapers ignore it.

## 4. DSAR (Data Subject Access Request) workflow

The right of a person to know what data DataSnoop holds about them.

Decision:

- Channel: <email address / web form URL>
- SLA from request to response: <X days> (GDPR Art. 12 default = 1 month)
- What we return: <full export of `person` row + every linked
  `person_link` + every `staatsblad_event` / `administrator` /
  `shareholder` / `affiliation` row referencing the person?>
- Authentication of the requester: <how do we verify they are who
  they say they are without making the request itself a privacy
  leak?>

Operational owner: <name / role>

## 5. Right-to-erasure / right-to-rectification

Erasure (Art. 17): the data-subject asks us to delete them.

- We can't delete the underlying public source data (KBO, Staatsblad,
  NBB filings) — those are public records published by the Belgian
  state. We can delete our **derived** `person` row + the
  `person_link` mappings, leaving the underlying source rows intact.
- After deletion, our resolver must NOT re-create the `person` row
  on the next ingest pass. Mechanism: `person_merge_log` writes a
  tombstone row; resolver checks the tombstone before creating new
  person rows. Tombstone uses a hash of the natural-key components
  so it doesn't itself store the person's name.

Decision:

- Tombstone TTL: ☐ permanent / ☐ <X years>
- Re-merge after tombstone: ☐ never (manual override only) / ☐
  allowed after operator review

Rectification (Art. 16): the data-subject says we got something
wrong (wrong name spelling, wrong company associated, etc.).

- Can we correct the derived record without breaking the audit chain
  back to the source row? Yes — `person.display_name_override`
  field; the original `name` from the source remains in
  `person_link.source_name_raw`.
- Operator authority to apply corrections: <name / role>

## 6. Manual merge / unmerge authority

Two scenarios:

- **Merge**: resolver thinks Jan De Smet (NV X director) and Jan
  De Smet (NV Y shareholder) are different people; operator decides
  they're the same.
- **Unmerge**: resolver auto-merged two rows; operator decides they're
  different people.

Decision:

- Who can merge: ☐ admin only / ☐ paid-tier user with rate limits
- Who can unmerge: ☐ admin only / ☐ subject themselves via DSAR-adjacent
  flow / ☐ both
- Merge audit trail: every manual merge writes to `person_merge_log`
  with operator identity + timestamp + reason. Unmerges too.
- Reversibility window: <X days> after a manual merge, unmerge is
  reversible without re-running the resolver.

## 7. Appeal path

When an automated decision is wrong (false merge, wrong role attribution,
wrong company association):

Decision:

- Channel: <where does the data subject complain?>
- SLA: <X days> from complaint to investigated decision
- Escalation: <DPO / lawyer / CEO contact>

## 8. Operational

- Decision-record owner: <operator name>
- Legal-memo signatory: <Belgian privacy lawyer name + firm>
- Last reviewed: <date>
- Next scheduled review: <date — every 12 months at minimum, or
  on any material change to KBO licence, GDPR enforcement guidance,
  or product surface>

---

**Until every section above has a written answer (not a placeholder),
the public Person URL does not ship.** Stub created during architecture
deep-dive r24. Track ramp-up status in `docs/data-architecture-phase-gates.md`.
