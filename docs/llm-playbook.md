# LLM Playbook

Living document for LLM findings across DataSnoop. If you learn something
a future session would benefit from knowing, APPEND it here. See
`memory/reference_llm_playbook.md` for the format rules.

## Format

Each finding has three parts:
1. **Finding** — one-sentence claim.
2. **Evidence** — the specific numbers/runs/files that back it.
3. **Takeaway** — what to do differently because of this.

Keep entries to ~5-15 lines. Group under the existing topic sections.


## Model choice

### Finding — Haiku 4.5 wins over Gemini Flash / Flash Lite / Haiku 3.5 on Belgian legal-gazette extraction

- **Evidence**: pilot phases 1b/1c/1j (see `plans/we-are-facing-an-swift-wilkinson.md`).
  Flash matched Haiku on overlapping fields (92 %) but Sonnet-judged
  Flash as baseline-wins on disagreements (hallucinated dates, split
  events). Haiku 3.5 failed overlap (89.7 %). Flash Lite pre-filter
  delivered 0 % skip on this corpus — no cost saving.
- **Takeaway**: Default to Haiku 4.5 for Belgian legal-text extraction.
  Don't re-test Flash / Haiku 3.5 / prompt-only JSON modes — they've
  already been rejected in pilot.


## Prompt engineering

### Finding — Tool-use mode forces schema conformance where prompt-only fails

- **Evidence**: pilot phase 1g produced 0 % schema compliance under
  prompt-only output instructions (Opus judged). Phase 1h with
  Anthropic `tool_choice={"type":"tool","name":...}` + strict
  `input_schema` enum delivered 25/25 schema-valid responses.
- **Takeaway**: For any structured-output task on this model family,
  use Anthropic tool-use. Don't ship prompt-based "return valid JSON"
  extractors to production.

### Finding — Few-shot examples beat prose exclusions for scope fences

- **Evidence**: Prose "ignore volmachten" instruction leaked into
  events 20/30 times in phase 1g. Adding 3 worked `<example>` blocks
  (volmacht-only, mixed volmacht+admin, auditor+rep) brought
  volmacht leakage to 0/26 in phase 1h.
- **Takeaway**: When the scope rule requires distinguishing superficially
  similar text (e.g. "appointment of X" appears in both in-scope admin
  events and out-of-scope signing powers), add at least 1 worked
  example per edge case.


## Caching

### Finding — Haiku 4.5's cache-prefix floor is 4,096 tokens, NOT the 1,024 documented for Sonnet/Opus

- **Evidence**: Phase 1h system prompt was ~1,840 tokens with
  `cache_control: ephemeral` on the last tool — 0/26 cache hits. Phase
  1i expanded the prompt to ~5,588 tokens (by adding 7 more worked
  examples) — 4/4 cache writes on run 1, 2/2 reads on run 2. Both
  OpenRouter and direct-Anthropic SDK measurements confirmed.
- **Takeaway**: For Haiku 4.5, pad system+tools above ~4,200 tokens
  before relying on prompt caching. Count via `anthropic.Anthropic().count_tokens()`,
  NOT character heuristics.

### Finding — `cache_control` goes on the LAST tool in the `tools` array

- **Evidence**: With tool-use, marking `cache_control` on the system
  string alone (Anthropic-native format) activated the cache across
  the system block; switching to `messages[0]` content-block form
  (OpenAI-compat) required the marker ALSO on the last tool in the
  `tools` array for the tools block to be cache-prefixed.
- **Takeaway**: Stick `cache_control: {"type":"ephemeral"}` on BOTH
  the system text block AND the last tool in `tools`. Copy-paste
  pattern from
  `backend/staatsblad_extraction/extractor.py::build_messages_payload`.

### Finding — OpenRouter drops the top-level Anthropic `system` string

- **Evidence**: First Phase-1i attempt passed `system="..."` at the
  top level per Anthropic SDK format. OpenRouter's OpenAI-compat
  proxy silently dropped the string. Rebuilt with `messages=[{"role":"system",
  "content":[...]}]` content-block form — caching worked.
- **Takeaway**: On OpenRouter, always put the system prompt as
  `messages[0]` with a content-block list. Anthropic-native `system`
  field is not forwarded.

### Finding — OpenRouter under-reports `cache_creation_input_tokens`

- **Evidence**: Direct-Anthropic SDK reports non-zero
  `cache_creation_input_tokens` on write calls; OpenRouter reports 0.
  Billing is still correct; only the observability signal is missing.
- **Takeaway**: Monitor `cache_read_input_tokens` on calls 2+ as the
  health signal — that field is reported by both transports. Don't
  trust the creation count on OpenRouter.


## Batch API

### Finding — Anthropic Batch API = 50 % off for async workloads

- **Evidence**: Phase D: 5-filing batch run cost $0.0135 vs $0.0269
  on regular API — 49.8 % saving (Anthropic's documented discount is
  50 %). Turnaround observed: ~8 minutes on a 5-filing test batch,
  well inside the 24h SLA.
- **Takeaway**: Use Anthropic batch API for any workload that can
  tolerate 1min-24h turnaround (backfills, recurring catch-up jobs).
  OpenRouter does NOT expose the batch endpoint with the discount —
  use the direct Anthropic SDK.


## PDF / OCR pipeline

### Finding — pdfplumber returns reversed text on Belgian gazette PDFs

- **Evidence**: Phase 1: 100 % of reversed-text filings. Root cause:
  unknown PDF font encoding. Swapping pdfplumber → fitz (PyMuPDF)
  resolved it 100 % of the time at zero cost.
- **Takeaway**: Use `fitz.open(..., filetype="pdf")` + `page.get_text()`
  for Belgian legal-gazette PDFs. Don't bother with pdfplumber on this
  corpus.

### Finding — Many "digital" PDFs have scanned-image bodies

- **Evidence**: Phase 1d measured 97.5 % of filings as having a thin
  digital header band with a scanned body. fitz returns only the
  header text (< 300 chars of body).
- **Takeaway**: Run fitz first, then fall back to OCR if post-strip
  body length < 300 chars. Code pattern:
  `backend/staatsblad_extraction/ocr_helper.py::extract_text_with_fallback`.

### Finding — EasyOCR is a viable free substitute for Tesseract

- **Evidence**: Tesseract installation needed admin rights on
  Hetzner; EasyOCR installed cleanly unprivileged via pip. CPU
  throughput: 5-15s per page at 200 DPI. Accuracy matched Tesseract
  on sampled filings.
- **Takeaway**: Use EasyOCR when the environment can't support
  Tesseract. Load the reader once per process (lazy singleton) —
  reader construction downloads ~100 MB of weights on first use.


## Evaluation methodology

### Finding — LLM-judge gates need to distinguish event-level vs formatting-level disagreements

- **Evidence**: Phase 1b raw "agreement rate" metric scored 94.4 %
  which tripped a fail gate, but the manual spot-check (Sonnet
  judging) found disagreements were mostly name-formatting nits
  (capitalisation, "De" vs "de"). Event-level sets were identical.
- **Takeaway**: When comparing two extractors on structured output,
  score the set of extracted events (not string equality) FIRST,
  then layer formatting checks on top. Use a structural diff on
  (event_type, person_name_normalized, role_code) before raising
  an auto-verdict.

### Finding — Optimization floor exists at ~20-25 % below naive projection

- **Evidence**: Pilot phases 1j + 1k together took the 110 k-filing
  projection from $276 (naive batch) → $215 (lean schema + V3 tool
  def + aggressive sectioner). Further sectioning gave diminishing
  returns; Flash Lite pre-filter gave 0 % skip.
- **Takeaway**: Budget a ~25 % reduction as "reasonable" when
  engineering for cost. Chasing more than that risks quality
  trade-offs.


## pgvector / embeddings

### Finding — IVFFlat with lists=100 is fine for 10k-500k rows

- **Evidence**: Used in `staatsblad_event_embedding` index (Stage 3,
  post-backfill target ~110k rows). IVFFlat needs at least some rows
  before lists probing helps; at 100k rows with lists=100, each list
  has ~1,000 rows — the sweet spot per pgvector docs.
- **Takeaway**: IVFFlat + `lists = N / 1000` for dataset sizes of
  10k-1M. For < 10k rows prefer HNSW (no training rows needed).

### Finding — 256-dim embeddings are 6× cheaper storage than 1536-dim

- **Evidence**: OpenAI's `text-embedding-3-small` supports
  `dimensions=256` parameter. At 256 floats × 4 bytes = 1 KB per
  vector vs 6 KB for full 1536. For DataSnoop's 2 M companies that's
  a 10 GB saving.
- **Takeaway**: Use `dimensions=256` everywhere embeddings are stored
  at scale. Quality loss is minimal for screening-style retrieval.


## Workflow patterns

### Finding — Cost guards + resume checkpoints are mandatory for batch backfills

- **Evidence**: Stage 3 `scripts/staatsblad_backfill.py` checks the
  Anthropic balance before each chunk and writes
  `staatsblad_backfill_progress` after each filing. Initial
  implementation excluded both 'extracted' and 'ocr_done' refs on
  resume — which stranded crashed chunks. Fixed to exclude only
  'extracted' so interrupted runs re-enter the pipeline.
- **Takeaway**: When checkpointing a multi-stage pipeline (e.g.
  OCR → LLM → persist), only "terminal success" states should bar
  re-entry on resume. Intermediate states like 'ocr_done' must be
  re-attempted.

### Finding — ON CONFLICT requires a UNIQUE CONSTRAINT (not UNIQUE INDEX) when using `ON CONSTRAINT <name>`

- **Evidence**: `staatsblad_event` dedup started as
  `CREATE UNIQUE INDEX idx_staatsblad_event_dedup ON ... (cols)` with
  the extractor using `ON CONFLICT ON CONSTRAINT idx_staatsblad_event_dedup`.
  Postgres rejected: "there is no unique or exclusion constraint
  matching the ON CONFLICT specification."
- **Takeaway**: Use `ON CONFLICT (<expression list>) DO NOTHING` when
  the target is a UNIQUE INDEX. `ON CONFLICT ON CONSTRAINT` only works
  for declared `CONSTRAINT ... UNIQUE` or `ADD CONSTRAINT ... UNIQUE`.

### Finding — FastAPI TierLimitMiddleware's path-based classifier needs one entry per logical endpoint

- **Evidence**: Stage 3 added `/api/events/search` (OpenRouter cost
  per call) and `/api/companies/{cbe}/events` (read-only DB). Only
  the first needs tier-counting; both slip past the limiter without
  an explicit `_classify_endpoint` rule.
- **Takeaway**: When adding new `/api/*` endpoints, grep for
  `_classify_endpoint` in `backend/main.py` and decide per-route
  whether it belongs in `ai_enrichments_per_day` / `export_per_day`
  / unlimited. Default-unlimited is load-bearing policy — only
  add to AI bucket when the endpoint actually calls an LLM/scraper.
