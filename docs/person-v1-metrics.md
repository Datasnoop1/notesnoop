# Person v1 Metrics

Date: 2026-05-02

Scope: internal-only deterministic resolver. Public `/person/<id>` ramp is
blocked until the policy record, legal memo, and stratified golden-set metrics
are all green.

## Internal Smoke Metrics

| Metric | Result |
| --- | --- |
| Tier A rule | `staatsblad_event` structured domicile anchor |
| Tier B rule | same normalized name plus common enterprise number with Tier A |
| Tier B sources | `administrator`, `shareholder`, `affiliation` |
| Tier C rule | residual singleton per source row |
| Existing links | preserved with `ON CONFLICT DO NOTHING` |
| Public URL flag default | off |

Production counts are recorded in
`docs/person-v1-internal-evidence-2026-05-02.md` after the Gate Y resolver run.

## Public-Ramp Golden Set

Status: blocked.

The public-ramp ~500-row stratified golden set has not been evaluated because
public URL work is not open. Required external gates remain:

- `docs/person-v1-policy.md` has a written answer in every section.
- Belgian privacy lawyer's memo is signed.
- Golden-set precision meets the policy threshold.
