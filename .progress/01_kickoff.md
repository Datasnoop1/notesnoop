# Stage 3 progress report #1 — kickoff

**Time**: 2026-04-18 (session start)
**Branch**: `claude/silly-jackson-43c832` (fresh worktree, cut from master db44457)
**Gmail connector**: not yet authenticated — reports written to files in
`.progress/` of this worktree until auth'd. Run `/mcp` in Claude Code
to connect the Gmail connector and future reports will be drafted to
`t.braet@gmail.com`.

## What's done

- Read full context: plan file, memory, pilot worktree reference code.
- Fresh worktree + feature branch confirmed cut from master.
- `src/schema.sql` — migrated obsolete regex-classified
  `staatsblad_event` table out of the way via a DO block; added the
  Stage-3 schema: `staatsblad_event` (8-category CHECK constraint),
  `staatsblad_publication_text`, `staatsblad_backfill_progress`,
  `staatsblad_event_embedding` (pgvector 256-dim).
- `backend/routers/open_data.py::company_events` rewired to the new
  column shape (thin compat alias; the real endpoint will be in
  staatsblad_events.py).
- `backend/staatsblad_extraction/` package scaffolded:
  `ocr_helper.py`, `boilerplate_stripper.py`, `prompt_v3.py` (V5 system
  prompt, ~5k tokens, above Haiku 4.5 cache floor),
  `__init__.py` with public re-exports.

## Next up (still within Phase 3a)

- `tool_v3.py` — Anthropic tool definition with strict enum + 60-char
  summary cap.
- `extractor.py` — orchestration: download PDF → OCR → strip → tool-use
  call → persist to Postgres, idempotent.
- `scripts/staatsblad_backfill.py` — batch-API backfill with
  checkpoint/resume + cost guard.
- `scripts/staatsblad_incremental.py` — daily regular-API wrapper.
- `backend/routers/staatsblad_events.py` — `/api/companies/{cbe}/events`
  and `/api/events/search` endpoints.
- Wire the new router into `main.py`, add the cron entry.

## Budget so far

- Research: ~$2.85 (from pilot, already spent)
- Stage 3 implementation: $0 so far (code-only)
- Planned: $10 smoke test + $180 Phase 4a (operator approval required)

No prod deploy or $ spend without your explicit go-ahead.
