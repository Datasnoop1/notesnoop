# Person v1 — Policy Decision Record

Status: **FILLED — 2026-05-02. Approved by operator. No external legal
memo required for launch (see §8).**

This is the operational policy that gates DataSnoop's public
`/person/<id>` URL. It defines what visitors can do, how data subjects
exercise their GDPR rights, who has merge/unmerge authority, and how
operational complaints are handled.

The two remaining gates on the `PERSON_PUBLIC_URL_ENABLED` feature flag
are now: (1) golden-set precision/recall metrics meeting the policy
threshold (still Codex's territory; ~500-row stratified set per the
deep-dive), and (2) `privacy@datasnoop.be` mailbox provisioned on the
Stalwart mail server (single small operational step — see §4).

Earlier framing required a signed Belgian privacy lawyer's memo as a
launch gate. Recalibrated 2026-05-02 against competitor precedent
(Companyweb, OpenTheBox both ship cross-company person aggregation
without published memos): the lawyer engagement remains *recommended*
for incident response (DSAR / complaint handling), not *required* for
launch.

---

## 1. Anonymous access

**Decision:** Anonymous access **allowed**. Anyone can view
`/person/<id>` without authentication.

**Rationale:** the underlying data (KBO directors/shareholders, NBB
filings, Staatsblad gazette events) is already public via Belgian
state registers and indexed by Google. Operational controls (rate
limits §2, robots-allowed §3, DSAR + erasure §4–5) compensate.
Consistent with competitor positioning — Companyweb and OpenTheBox
both expose person aggregations to anonymous visitors.

---

## 2. Rate limits — per-IP and per-account

**Decision:** **Mirror existing company-profile rate limits**. The
`/api/people/<id>` and frontend `/person/<id>` paths inherit the same
per-tier per-day caps as `/api/companies/<cbe>` profile reads. No new
rate-limit bucket; same `TierLimitMiddleware` classifier.

**Implementation:** add `/api/people/<id>` and `/person/<id>` to the
existing rate-counting endpoint list in `backend/main.py`. Per-tier
caps unchanged.

**Backstop:** nginx `limit_req` zone covering `/person/*` as
defence-in-depth, same shape as `/companies/*`.

---

## 3. Robots / noindex / sitemap

**Decision:**
- `robots.txt`: **Allow** `/person/`
- meta robots tag on Person pages: default `index, follow`
- Sitemap: include person profiles

**Rationale:** Google indexing brings SEO traffic, which is desirable.
Source data is already publicly indexed at the underlying registers;
the aggregated profile doesn't expose any fact that isn't already
findable separately. Bots accessing `/person/<id>` still hit the
rate limits in §2.

---

## 4. DSAR (Data Subject Access Request) workflow

**Decision:**
- **Channel:** `privacy@datasnoop.be`
- **SLA:** 30 days from request to response (GDPR Article 12 default)
- **What we return:** full export of the requester's `person` row +
  every linked `person_link` row (with source-table pointers) + the
  source rows in `staatsblad_event`, `administrator`, `shareholder`,
  and `affiliation` that reference the person
- **Identity verification:** the operator (Tom) reviews every DSAR
  personally. Identity verified by reply-with-ID-document (Belgian
  passport or eID card scan, with non-essential fields redacted by the
  requester acceptable).
- **Cc:** every DSAR forwarded to the operator's primary inbox
  alongside the privacy mailbox so DSARs cannot be missed.

**Open implementation item:** `privacy@datasnoop.be` mailbox needs to
be provisioned on the existing Stalwart mail server (5-minute config
change; same pattern as `claude@datasnoop.be`). Deferred to
pre-flag-flip operational checklist.

**Operational owner:** operator (Tom Braet, Invm BV).

---

## 5. Right-to-erasure / right-to-rectification

### Erasure (Article 17)

**Decision:**
- **Tombstone TTL:** 5 years. After erasure, the resolver records a
  tombstone keyed by a hash of the person's natural-key components
  so the next ingest pass does not re-create the person row. The
  tombstone hash does NOT itself store the person's name in
  recoverable form.
- **Re-merge after tombstone expiry:** allowed only after explicit
  operator review. Not automatic. Operator decides per case whether
  the tombstoned identity may be re-resolved by the next ingest pass.

**Mechanism:** erasure deletes the `person` row + all `person_link`
rows pointing at it. The underlying `administrator`, `shareholder`,
`staatsblad_event`, etc. source rows are NOT deleted (those are
faithful copies of public records published by Belgian authorities).
A tombstone row is written to `person_merge_log` with `op_kind =
'tombstone'` and the natural-key hash.

### Rectification (Article 16)

**Decision:** rectification authority is **operator-only**.

**Mechanism:** the operator can write a `person.display_name_override`
for cosmetic corrections (spelling, accent variants, capitalization).
The original source name remains in `person_link.source_name_raw`
for audit trail. Substantive corrections (wrong role attribution,
wrong company association) go through the operator's manual review
channel — see §6 unmerge flow.

---

## 6. Manual merge / unmerge authority

**Decision:**
- **MERGE authority:** admin only (operator). End users cannot trigger
  merges.
- **UNMERGE authority:** admin only (operator). End users *can*
  report perceived errors via `privacy@datasnoop.be` (same channel as
  DSAR / appeals); operator reviews and unmerges if the report is
  valid.
- **Reversibility window:** 30 days. Within 30 days of a manual merge,
  unmerge restores the prior state without re-running the resolver.
  Beyond 30 days the unmerge requires the operator to re-decide
  manually.

**Mechanism:** every merge + unmerge writes a row to
`person_merge_log` with the operator identity, timestamp, reason, and
the list of `person_link.id` values that switched cluster. The 30-day
reversibility uses the merge-log entry to roll back.

---

## 7. Appeal path

**Decision:**
- **Channel:** `privacy@datasnoop.be` (same as DSAR — single mailbox
  handles all data-subject communications).
- **SLA:** 30 days from receipt to substantive response.
- **Escalation:** none. The operator (Tom) personally reviews and
  resolves every appeal. If a case is genuinely intractable, operator
  may engage external legal counsel ad-hoc, but no standing escalation
  contract is in place.

**Scope:** appeals cover any automated decision the data subject
disputes — wrong merge, wrong role attribution, wrong company
association, perceived inaccuracy in displayed data.

---

## 8. Operational

- **Decision-record owner:** Tom Braet (operator), Invm BV
- **Legal-memo signatory:** **internal review only.** No external
  Belgian privacy-lawyer engagement at this time. Operator may engage
  privacy counsel on retainer for incident-response support but does
  not require a pre-launch memo.
- **Last reviewed:** 2026-05-02
- **Next scheduled review:** 2027-05-02 (annual review cycle; advance
  if Belgian DPA guidance materially changes or if operational
  incidents reveal policy gaps)

### Public-ramp residual risk

The 2026-05-02 golden-set measurement met the >=0.99 precision floor
(528 labelled mention-pairs, precision 1.00, false positives 0). It also
identified 80 false negatives, all in the foreign/no-domicile repeat-positive
stratum. Those people may see incomplete or fragmented role history across
multiple Person pages in v1. This is an accepted launch tradeoff: DataSnoop
gates the public ramp on precision to avoid false merges, while explicitly
accepting recall limitations for launch. DataSnoop prefers singleton pages over
speculative merges until a future resolver version can safely lift those rows.
DSAR, rectification, and appeal requests for this case use
`privacy@datasnoop.be` and follow the 30-day operator-owned process in §4 and
§7.

---

## Pre-flag-flip operational checklist

Before flipping `PERSON_PUBLIC_URL_ENABLED=true` on production, the
following operational items must be in place:

- [x] `privacy@datasnoop.be` mailbox provisioned on Stalwart mail server
      *(Stalwart list principal id=11 created 2026-05-02)*
- [x] Forwarding rule from `privacy@datasnoop.be` → operator primary inbox
      *(externalMembers=[t.braet@gmail.com] on the list principal;
      direct SMTP forward, no local copy stored)*
- [x] `nginx/default.conf` adds `limit_req` zone for `/person/*`
      (same shape as `/companies/*`) per §2
      *(validated 2026-05-02; see
      `docs/person-v1-public-checklist-evidence-2026-05-02.md`)*
- [x] Frontend `/person/<id>` page links to `privacy@datasnoop.be`
      footer for DSAR/appeal access per §4 + §7
      *(implemented 2026-05-02)*
- [x] `robots.txt` updated per §3 (`Allow: /person/`); sitemap
      generator includes person profiles
      *(implemented 2026-05-02; feed remains flag-gated until launch)*
- [x] Golden-set precision/recall measurement complete (Codex
      deliverable; ~500-row stratified set; threshold per the
      deep-dive Person v1 spec)
      *(528 labelled mention-pairs measured 2026-05-02; precision 1.00
      against >=0.99 floor; see
      `docs/person-v1-golden-set-metrics-2026-05-02.md`)*

Once all six items are green AND the operator has reviewed this
policy doc one final time, the `PERSON_PUBLIC_URL_ENABLED` flag flips
and the public Person URL goes live.

---

*Filled 2026-05-02. Recalibrated against competitor precedent (Belgian
privacy lawyer's pre-launch memo is recommended-not-required).
Internal review only suffices for launch; lawyer engagement on
retainer recommended for post-launch incident response.*
