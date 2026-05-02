# Person v1 Metrics

Date: 2026-05-02

Scope: internal-only deterministic resolver plus public-ramp golden-set
measurement. Public `/person/<id>` launch is gated by the policy record,
stratified golden-set precision, and operator-approved production flag flip.

## Internal Smoke Metrics

| Metric | Result |
| --- | --- |
| Tier A rule | `staatsblad_event` structured domicile anchor |
| Tier B rule | same normalized name plus common enterprise number with Tier A |
| Tier B sources | `administrator`, `shareholder`, `affiliation` |
| Tier C rule | residual singleton per source row |
| Existing links | preserved with `ON CONFLICT DO NOTHING` |
| Public URL flag default | off |
| Staging person rows | 1,158,921 |
| Staging person links | 1,171,963 |
| Staging Tier A links | 15,671 |
| Staging Tier B links | 12,188 |
| Staging Tier C links | 1,144,104 |
| Staging affiliation links | 49,975 |
| Staging merge log rows | 0 |
| Production person rows | 1,173,595 |
| Production person links | 1,186,678 |
| Production Tier A links | 15,671 |
| Production Tier B links | 12,229 |
| Production Tier C links | 1,158,778 |
| Production affiliation links | 53,081 |
| Production merge log rows | 0 |

Production evidence is recorded in
`docs/person-v1-internal-evidence-2026-05-02.md`.

## Public-Ramp Golden Set

Status: green for precision.

The public-ramp golden set was evaluated on 2026-05-02. Evidence:
`docs/person-v1-golden-set-metrics-2026-05-02.md`; sampled pair set:
`docs/person-v1-golden-set-2026-05-02.json`.

| Metric | Result |
| --- | ---: |
| Labelled mention-pairs | 528 |
| Precision floor | 0.99 |
| Measured precision | 1.00 |
| Measured recall | 0.78022 |
| False positives | 0 |

The precision gate is green. Recall is tracked as an operational residual risk:
all 80 false negatives come from foreign/no-domicile repeated administrator
mentions that v1 keeps as Tier-C singleton pages rather than speculative
merges. This can produce incomplete or fragmented role history for affected
people, and the DSAR/appeal process is the v1 correction path.

Launch gates now recorded for the public ramp. The safety-critical gate is the
precision floor because it protects against false merges between unrelated
people; recall limitations are an accepted operational completeness risk for
v1.

- Policy decision record complete.
- `privacy@datasnoop.be` mailbox and forwarding complete.
- `/person/*` nginx rate-limit backstop verified.
- DSAR/appeal footer, robots allow rule, and flag-gated sitemap complete.
- Golden-set precision >=0.99 complete.
- Operator-approved production flag flip and smoke evidence remain the final
  tail step.

Residual risk: foreign/no-domicile roles can remain fragmented in v1. That risk
is explicitly accepted for public launch because the precision floor protects
against the higher-risk failure mode: false merges between unrelated people.
