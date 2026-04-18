# Stage 3 progress report #2 — mid-implementation

**Time**: 2026-04-18 (approx +3h from kickoff)
**Branch**: `claude/silly-jackson-43c832`
**Commits so far**: 4 on this branch
**Delivery note**: SSH send to Hetzner Stalwart is denied by default
policy ("Production Reads rule — needs explicit operator
authorization"). Gmail MCP still requires your one-off auth. Until
one of those unblocks, progress reports land here in `.progress/`.

## What's landed

| Phase | Status | One-line |
|---|---|---|
| 3a | done | Schema + extraction module + backfill + batch-every-2d + /events API |
| 3b | done | `/structure` merges NBB + Staatsblad with provenance badges; `/extract-admins` rewired (no LLM, reads from event store) |
| 3c | done | `/people/{name}/connections` + `/people/search` union Staatsblad admins; network graph depth-0 gains Staatsblad-sourced nodes |
| 3d | done | `/summarize-publications` synthesises from structured events when ≥3 available (no LLM call); ai_insights_pipeline gets `<recent_filings>` context block |
| 3e | todo | Embeddings backfill script exists (3a); frontend search tab still outstanding |
| Addendum 3 | done | Every-2-days batch cadence: `staatsblad_batch_every_2d.py` + cron `0 4 */2 * *` |

## What still needs doing

1. Phase 3e frontend: search tab / event-search UI hitting
   `/api/events/search` (backend endpoint already ships with
   keyword-only fallback when embeddings are empty).
2. Run the two review agents (correctness + security) in parallel.
3. Fix any CRITICAL issues, merge to master.
4. `scripts/deploy_staging.sh` → smoke test (20 known companies, <$10).
5. Wait for operator approval → prod deploy.
6. Wait for operator approval → Phase 4a backfill.

## Cost tracking

- Implementation so far: **$0** (code-only, no LLM calls).
- Cap for the staging smoke test: **$10**.
- Phase 4a backfill cap (after your prod approval): **$180**
  (expected ~$143 per the plan).

## Memory updates done

- `project_staatsblad_admin_tracker.md`: appended Addendum 3 note
  about the 2-day batch cadence.
- `reference_stalwart_mail.md`: corrected the port-25 outbound
  status (now reflects that outbound is OPEN on the Hetzner host).

## Expected next report

After the review agents return + Phase 3e frontend lands + we merge
to master.
