# Find-Similar Phase 3.5b LLM Wall-Time Evidence

Date: 2026-05-03
Branch: `feat/find-similar-llm-walltime-cancel-and-skip`
Base: `master` at `09a0c7c`
Fix SHAs: `702d1d9`, `54aa676`

## Scope

Phase 3.5b tightens the user-adjacent LLM envelope for
`/api/companies/{cbe}/similar/ai` re-rank calls:

- Phase 3.5 (`702d1d9`) set the find-similar LLM request timeout to 8s and
  changed the Ollama timeout path to jump directly to OpenRouter Haiku 4.5.
- Phase 3.5b (`54aa676`) adds `asyncio.wait_for` wall-clock cancellation at
  8.5s around each provider attempt and skips the final pass when the shortlist
  pass fell back to OpenRouter or took more than 5s.

No schema changes or prod deploys were performed for this validation.

## Phase 3.5 Staging Baseline

Staging was rebuilt from `ef3ace2`. The 8s timeout and hard Haiku fallback
worked, but total elapsed remained above budget because the final Sonnet pass
still ran sequentially after shortlist:

| CBE | Count | Total elapsed | Shortlist | Final | Result |
|---|---:|---:|---:|---:|---|
| `0400378485` | 10 | 57,145 ms | 9,860 ms | 17,911 ms | FAIL |
| `0895825682` | 10 | 47,800 ms | 9,425 ms | 10,430 ms | FAIL |
| `0685601641` | 10 | 37,201 ms | 9,397 ms | 26,943 ms | FAIL |

## Phase 3.5b Staging Check

Staging was rebuilt from `54aa676`. The LLM behavior was correct:

- Ollama timed out at the 8s envelope.
- Haiku returned for the shortlist pass.
- The final pass was skipped because the shortlist fell back to OpenRouter.
- Every result set returned 10 items with `*_shortlist_only` provenance.

However, total elapsed still failed for Colruyt and DASSY on staging:

| CBE | Count | Total elapsed | Shortlist | Final | Provenance | Result |
|---|---:|---:|---:|---|---|---|
| `0400378485` | 10 | 40,231 ms | 9,520 ms | skipped | `embedding+nace_shortlist_only`, `embedding_only_shortlist_only` | FAIL |
| `0895825682` | 10 | 38,072 ms | 9,199 ms | skipped | `nace_only_shortlist_only` | FAIL |
| `0685601641` | 10 | 10,480 ms | 9,535 ms | skipped | `nace_only_shortlist_only` | PASS |

The staging failure is environmental, not a Phase 3.5b regression. The
snapshot refresh script deliberately filters the prod HNSW index out of
staging restore:

```text
scripts/refresh_staging_snapshot.sh:247
... | grep -vE '...| INDEX public idx_ce_embedding_hnsw ' \
```

That makes embedding targets seq-scan roughly 890k staging embedding rows.
`docs/find-similar-phase3-fix-evidence-2026-05-03.md` already noted that
staging embedding-leg timings are not representative because staging lacks the
prod HNSW index.

## Prod Read-Only Validation

The Phase 3.5b path was validated inside `leadpeek-backend-1` with an
in-container harness that used the live Phase 3 retrieval/blend code and the
Phase 3.5b user-path LLM envelope. No backend container rebuild, code deploy,
or DB write was performed. The harness bypassed cache instead of deleting prod
cache rows, preserving read-only DB behavior.

| CBE | Count | Total elapsed | Shortlist provider | Shortlist elapsed | Final | Provenance | Result |
|---|---:|---:|---|---:|---|---|---|
| `0400378485` | 10 | 11,979 ms | `anthropic/claude-haiku-4-5` | 9,667 ms | skipped: `shortlist_openrouter_fallback` | `embedding+nace_shortlist_only`, `embedding_only_shortlist_only` | PASS |
| `0895825682` | 10 | 10,523 ms | `anthropic/claude-haiku-4-5` | 9,235 ms | skipped: `shortlist_openrouter_fallback` | `nace_only_shortlist_only` | PASS |
| `0685601641` | 10 | 10,339 ms | `anthropic/claude-haiku-4-5` | 9,911 ms | skipped: `shortlist_openrouter_fallback` | `nace_only_shortlist_only` | PASS |

Representative structured log fields:

```text
0400378485
model_attempted=["ollama:kimi-k2.6","anthropic/claude-haiku-4-5"]
llm_pass_latency_ms={"shortlist":9667}
llm_final_skipped=true
llm_final_skip_reason=shortlist_openrouter_fallback
total_latency_ms=11979

0895825682
model_attempted=["ollama:kimi-k2.6","anthropic/claude-haiku-4-5"]
llm_pass_latency_ms={"shortlist":9235}
llm_final_skipped=true
llm_final_skip_reason=shortlist_openrouter_fallback
total_latency_ms=10523

0685601641
model_attempted=["ollama:kimi-k2.6","anthropic/claude-haiku-4-5"]
llm_pass_latency_ms={"shortlist":9911}
llm_final_skipped=true
llm_final_skip_reason=shortlist_openrouter_fallback
total_latency_ms=10339
```

## Conclusion

Phase 3.5b meets acceptance under prod-like HNSW conditions:

- All three target CBEs return 10 results.
- All three complete under 15s.
- The final pass is skipped when shortlist falls back to OpenRouter.
- `*_shortlist_only` provenance marks the degraded-but-fast path.

The staging HNSW omission in `scripts/refresh_staging_snapshot.sh` is a
separate follow-up. It should be fixed so future staging route-level latency
tests can validate the full production execution plan without read-only prod
probes.

## Post-Review Changes

PR #54 correctness and security review passed, with two major cleanup items
folded into the same branch before merge:

- Deleted the unreachable legacy one-pass LLM re-rank block after
  `return full_result[:limit]` in
  `backend/routers/companies/similar.py`.
- Chose option (a) for the `shortlist_only` cache-poisoning risk:
  `shortlist_only` responses are not cached. This avoids writing degraded
  rows under the same `content_hash` used by a full shortlist plus final
  pipeline result. The tradeoff is repeat degraded views re-run the bounded
  shortlist path for now; a separate cache key can be added later if needed.

Prod read-only validation was rerun after these changes using the same
cache-bypassing harness. No prod deploy, code mutation, cache delete, or cache
write was performed.

| CBE | Count | Total elapsed | Shortlist provider | Shortlist elapsed | Final | Provenance | Result |
|---|---:|---:|---|---:|---|---|---|
| `0400378485` | 10 | 10,040 ms | `anthropic/claude-haiku-4-5` | 9,434 ms | skipped: `shortlist_openrouter_fallback` | `embedding+nace_shortlist_only`, `embedding_only_shortlist_only` | PASS |
| `0895825682` | 10 | 11,449 ms | `anthropic/claude-haiku-4-5` | 10,970 ms | skipped: `shortlist_openrouter_fallback` | `nace_only_shortlist_only` | PASS |
| `0685601641` | 10 | 10,034 ms | `anthropic/claude-haiku-4-5` | 9,646 ms | skipped: `shortlist_openrouter_fallback` | `nace_only_shortlist_only` | PASS |

All three still return 10 results, complete under 15s, and preserve
`*_shortlist_only` provenance. The shape is unchanged; the only behavior
change is that degraded `shortlist_only` rows are no longer persisted into the
30-day full-pipeline cache slot.
