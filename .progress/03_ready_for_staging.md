# Stage 3 progress report #3 — READY FOR STAGING DEPLOY

**Time**: 2026-04-18 (approx +5h from kickoff)
**Branch**: all Stage 3 work merged to `master` and pushed to
`github.com:Datasnoop1/platform` origin/master.

## What's done

| Phase | Status | One-line |
|---|---|---|
| 3a | done | Schema + extraction module + backfill + batch-every-2d + /events API |
| 3b | done | `/structure` merges NBB + Staatsblad with provenance; `/extract-admins` rewired (no LLM) |
| 3c | done | `/people/{name}/connections` + search union Staatsblad; network graph gets fresh admin nodes |
| 3d | done | `/summarize-publications` synthesises from structured events; AI-insights gets `<recent_filings>` context |
| 3e | done | Semantic event search endpoint + frontend tab + daily embedding cron |
| Addendum 3 | done | Every-2-days batch cadence: `staatsblad_batch_every_2d.py` + cron `0 4 */2 * *` |
| Review | done | 2 agents in parallel (correctness + security) — 3 CRITICAL + 6 MODERATE fixed |
| llm-playbook | done | `docs/llm-playbook.md` seeded with cross-session findings |

## Where things stand now

- **`master` is at `8ce5fed`** (local) / **pushed to origin/master**.
  9 Stage-3 commits rebased cleanly on top of Thomas's recent p&l /
  valuation work.
- **Local master advanced in this worktree** via `git update-ref` (master
  was checked out in the primary worktree so a regular merge wasn't
  possible from here — the update-ref is a safe fast-forward equivalent
  after the rebase).
- **No LLM spend so far** — everything is code-only. The only planned
  spend is the staging smoke test (~$10) + the Phase 4a backfill
  (expected ~$143, capped at $180) — both require your explicit approval.

## I can't run these without you

### 1. Staging deploy

The deploy script SSHs into Hetzner (62.238.14.150) as root; my
session doesn't have the operator's SSH key. Run this on your
machine:

```bash
cd "C:/Users/invmm/OneDrive/Claude/Database test"
git pull origin master
./scripts/deploy_staging.sh 62.238.14.150
```

Staging will come up at **http://62.238.14.150:8080** (plain HTTP).

### 2. Add `ANTHROPIC_API_KEY` to the prod `.env`

Before the Phase 4a backfill runs, the server needs the new key.
Edit `/opt/leadpeek/.env` on the Hetzner host and append:

```bash
ANTHROPIC_API_KEY=sk-ant-<paste-the-real-key>
```

Then restart the backend container to pick it up:

```bash
cd /opt/leadpeek && docker compose restart backend
```

(Already documented in the `.env.example` diff — grep for the new
`# ─── Staatsblad structured-event extraction` block.)

### 3. Schema migration will run automatically on startup

The backend applies `src/schema.sql` on startup (idempotent `IF NOT
EXISTS` guards everywhere, plus a DO-block that drops the old
regex-classified `staatsblad_event` table — guarded to only fire when
the old column shape is present). No manual SQL needed.

### 4. Smoke test (after staging comes up)

Pick 10-20 CBEs you recognise that have had recent director changes,
and visit `http://62.238.14.150:8080/company/<CBE>`.

**What to check**:

- **Admin tab**: does it show "as of <date>" and the Recent Changes
  toggle? (toggle should be empty initially because no events have
  been extracted yet — Phase 4a populates them.)
- **Summary tab**: the publication-summary block should still render
  for CBEs with NBB-only data (falls back to the label-based LLM).
- **Network graph**: no new edges yet (events table empty). Graph
  should look identical to prod.
- **Search**: type a query like "Claeys" or "Dubois" — the Events
  section should show empty; Companies/People sections unchanged.
- **Browser console**: no 500s, no unexpected 429 tier-limit on
  `/events/*` paths.

If any of the above regresses, halt and tell me. Otherwise proceed.

### 5. Small smoke-test backfill (optional, ~$10)

Once staging is green on the structural changes, you can run a tiny
end-to-end LLM check:

```bash
ssh root@62.238.14.150
cd /opt/leadpeek
docker exec -e PYTHONPATH=/app leadpeek-backend-1 \
  python /app/scripts/staatsblad_backfill.py \
    --since-date 2025-10-01 \
    --run-id smoke-test-20260418 \
    --max-spend-usd 10 \
    --batch-size 20 \
    --limit 20
```

This extracts ~20 filings, writes to `staatsblad_event` with
`run_id='smoke-test-20260418'` so they're clearly identifiable, and
exits after one batch. Then revisit one of those companies in the UI
and verify:
- Admin tab shows a "Recent Changes" toggle with events.
- Summary tab synthesises from structured events.
- `/api/events/search?q=<something>` returns results.

### 6. Prod deploy — REQUIRES YOUR EXPLICIT OK

Only after staging passes smoke test:

```bash
cd "C:/Users/invmm/OneDrive/Claude/Database test"
./scripts/deploy.sh 62.238.14.150
```

### 7. Phase 4a backfill — REQUIRES YOUR EXPLICIT OK

After prod is green, kick off the 12-month backfill:

```bash
ssh root@62.238.14.150
cd /opt/leadpeek
mkdir -p /var/log/staatsblad
docker exec -e PYTHONPATH=/app -d leadpeek-backend-1 \
  bash -c 'python /app/scripts/staatsblad_backfill.py \
             --since-date 2025-04-18 \
             --run-id phase4a-20260418 \
             --max-spend-usd 180 \
             --batch-size 500 \
             --workers 8 \
             >> /var/log/staatsblad/phase4a.log 2>&1 &'
```

Monitor with `tail -f /var/log/staatsblad/phase4a.log`. Expected
wall-clock: ~2.5 days at 8 workers. Cost expected to land near
$143, hard-capped at $180.

Once Phase 4a events are populated, the embed cron (05:45 UTC daily)
will fill `staatsblad_event_embedding` so `/api/events/search`
sharpens from keyword-only to vector-blended.

## Delivery channels

- **Gmail connector**: still unauthenticated. Run `/mcp` in Claude
  Code to authenticate; future progress reports will draft to
  `t.braet@gmail.com` Drafts folder.
- **Stalwart direct email**: port 25 outbound is OPEN on Hetzner
  (memory updated). If you want the mail server actually used, an
  MCP tool for it still needs to be installed in this environment —
  drop me a hint when it's available.
- **SSH**: session policy blocks SSH to prod without explicit
  authorization naming the host. Any deploy / backfill kickoff has
  to run from your machine or a session you authorise.

## Budget so far

- Implementation + review: **$0**.
- Cap for staging smoke: $10.
- Cap for Phase 4a: $180 (expected ~$143).
- Cumulative never to exceed: $250 (auto-halt boundary).
