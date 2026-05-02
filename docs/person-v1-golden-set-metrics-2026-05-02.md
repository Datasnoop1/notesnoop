# Person v1 Golden-Set Metrics - 2026-05-02

Scope: public-ramp measurement for the deterministic Person v1 linker on
production data. The public URL flag was still OFF while this measurement ran.

## Gate Result

| Metric | Result |
| --- | ---: |
| Labelled mention-pairs | 528 |
| Precision floor for auto-merge/public launch | 0.990000 |
| Measured precision | 1.000000 |
| Precision floor met | YES |
| Measured recall | 0.780220 |
| F1 | 0.876543 |
| True positives | 284 |
| False positives | 0 |
| True negatives | 164 |
| False negatives | 80 |

Decision: **GREEN for the public-ramp precision gate**. The deterministic
linker produced zero false merges in this 528-pair stratified set, meeting the
>=0.99 precision floor.

Residual product risk: precision is not the only quality dimension. The 80
false negatives in the foreign/no-domicile stratum mean some people can have
incomplete or fragmented role history across multiple Person pages in v1. This
is an explicit operational tradeoff: v1 avoids speculative merges because a
false merge between unrelated people is the higher-risk public failure mode.
The fragmentation risk is accepted for launch and is covered operationally by
the DSAR/rectification/appeal path in `docs/person-v1-policy.md`; future v1.1+
resolver work should target this recall gap.

## Reproducibility

- Evaluator: `scripts/person_golden_set_eval.py`
- Output set: `docs/person-v1-golden-set-2026-05-02.json`
- Production command, run inside the restricted `backend` container so the
  script uses only `DATABASE_URL` from the container environment and the DSN is
  never printed:

  ```bash
  python /tmp/person_golden_set_eval.py \
    --database-url-env DATABASE_URL \
    --output /tmp/person-v1-golden-set-2026-05-02.json
  ```

The committed JSON stores link ids, source tables, confidence bands, labels,
predictions, and rationales. It intentionally omits raw names and source primary
keys, enterprise numbers, and person UUIDs. Access to the artifact follows the
repository's normal access controls.

Artifact privacy verification:

```bash
python - <<'PY'
import json
d = json.load(open('docs/person-v1-golden-set-2026-05-02.json', encoding='utf-8'))
allowed = {
    'stratum', 'left_link_id', 'right_link_id', 'left_source_table',
    'right_source_table', 'left_confidence', 'right_confidence',
    'expected_same', 'predicted_same', 'rationale'
}
for i, r in enumerate(d['records']):
    assert set(r) == allowed, (i, sorted(set(r) ^ allowed))
print(len(d['records']), 'records schema-clean')
PY
```

The evaluator also supports the same check directly:

```bash
python scripts/person_golden_set_eval.py \
  --validate-artifact docs/person-v1-golden-set-2026-05-02.json
```

## Strata

| Stratum | Count | TP | FP | TN | FN |
| --- | ---: | ---: | ---: | ---: | ---: |
| common_belgian_surname_tier_a_positive | 14 | 14 | 0 | 0 | 0 |
| tier_a_structured_domicile_positive | 80 | 80 | 0 | 0 | 0 |
| multilingual_accent_variant_positive | 50 | 50 | 0 | 0 | 0 |
| legal_representative_affiliation_positive | 70 | 70 | 0 | 0 | 0 |
| tier_b_admin_shareholder_cooccurrence_positive | 70 | 70 | 0 | 0 | 0 |
| foreign_or_no_domicile_repeat_positive | 80 | 0 | 0 | 0 | 80 |
| same_city_homonym_negative | 11 | 0 | 0 | 11 | 0 |
| ambiguous_same_enterprise_negative | 70 | 0 | 0 | 70 | 0 |
| false_merge_trap_same_name_different_anchor_negative | 23 | 0 | 0 | 23 | 0 |
| same_name_different_anchor_negative | 60 | 0 | 0 | 60 | 0 |

## Notes

- The required high-risk categories are covered: common Belgian surnames,
  multilingual/accent variants, foreign/no-domicile directors,
  legal-representative affiliation chains, same-city homonyms, and false-merge
  traps.
- Three rare trap categories had fewer available production examples than their
  requested quotas: common Belgian surname Tier-A positives short by 6,
  same-city homonym negatives short by 9, and false-merge-trap common-name
  negatives short by 7. Broader Tier-A/Tier-B support strata brought the final
  labelled set to 528 pairs. The shortfalls reduce coverage depth in those
  rare edge cases, but they do not change the measured launch gate: the
  negative trap strata that were available produced 0 false positives, and the
  broader same-name/different-anchor stratum adds 60 more false-merge checks.
- All 80 false negatives came from the foreign/no-domicile repeat-positive
  stratum, where v1 deliberately prefers singleton Tier-C pages over
  speculative merges. These misses are an operational completeness risk, not a
  false-merge precision failure. They remain visible in launch evidence so the
  public ramp is understood as "high precision, incomplete recall" rather than
  "fully complete identity history."
