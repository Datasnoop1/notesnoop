"""Find-similar route guards.

Phase 4 / 2026-05-04 — pins the load-bearing behaviours we shipped in
PRs #54 (wall-clock backstop + shortlist-only), #57 (drop revenue gate
in NACE leg + 100-row exhaustive list), #58 (relaxed activity-overlap
floors), and #59 (db pool ping + WALL_BACKSTOP_S rename + staging
HNSW rebuild).

Tests are deliberately source-level rather than runtime — they read
files and assert on substrings — to avoid the live-PG / live-LLM
dependencies a real route test would need. The assertions here lock
in the structural guarantees so a future refactor can't silently undo
them.
"""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Route surface (similar.py)
# ---------------------------------------------------------------------------

def test_endpoint_limit_accepts_up_to_100():
    """The /similar/ai endpoint allows clients to request up to 100 rows
    so the exhaustive-list view (operator's 2026-05-04 ask) works."""
    src = _read("backend/routers/companies/similar.py")
    assert "limit: int = Query(10, ge=1, le=100)" in src


def test_max_ranked_items_is_100():
    """We cache up to MAX_RANKED_ITEMS so 'find more' (and the new 100-
    cap exhaustive view) hit cache rather than re-running the LLM."""
    src = _read("backend/routers/companies/similar.py")
    assert "MAX_RANKED_ITEMS = 100" in src


def test_result_fields_expose_zipcode_and_nace_code():
    """Frontend needs zipcode + nace_code to support sortable columns
    (planned follow-up). Keep them in the response shape."""
    src = _read("backend/routers/companies/similar.py")
    assert '"zipcode"' in src
    assert '"nace_code"' in src


def test_shortlist_only_path_skips_cache_write():
    """When the shortlist call falls back to OpenRouter or runs slow,
    the final pass is skipped and the result is NOT cached. Caching a
    degraded result would pin the user (and every subsequent viewer)
    on a low-quality ranking for up to 30 days."""
    src = _read("backend/routers/companies/similar.py")
    # Find the shortlist_only branch and confirm it returns without
    # calling _upsert_cache. If a future refactor adds a cache write
    # there, this test will fire.
    branch_start = src.index('log_event["degraded"] = "shortlist_only"')
    branch_end = src.index("final_limit = max(5, min(MAX_RANKED_ITEMS,", branch_start)
    branch_text = src[branch_start:branch_end]
    assert "_upsert_cache" not in branch_text


def test_shortlist_only_skip_threshold_is_five_seconds():
    """Phase 3.5b acceptance criterion: skip the final LLM pass when the
    shortlist took longer than 5 seconds. 5s leaves enough budget for
    the final pass to also run inside the 15s end-to-end target."""
    src = _read("backend/routers/companies/similar.py")
    assert "shortlist_elapsed_ms > 5000" in src


def test_apply_llm_ranking_supports_backfill_pool():
    """The 100-row view needs to extend past the LLM-ranked top 15 with
    blended candidates that get template reasons. The optional
    backfill_from kwarg is what makes that work."""
    src = _read("backend/routers/companies/similar.py")
    assert "backfill_from: list[dict] | None = None" in src
    assert "backfill_from=candidates" in src


# ---------------------------------------------------------------------------
# Retrieval (retrieval.py)
# ---------------------------------------------------------------------------

def test_nace_leg_uses_left_join_not_inner():
    """retrieve_by_nace must NOT inner-join financial_latest — that
    silently drops 99% of NACE peers in sectors that file abridged
    accounts (real-estate agencies, accountants, doctors, lawyers)."""
    src = _read("backend/retrieval.py")
    nace_fn_start = src.index("def retrieve_by_nace(")
    nace_fn_end = src.index("# ───", nace_fn_start)
    nace_fn = src[nace_fn_start:nace_fn_end]
    assert "LEFT JOIN financial_latest" in nace_fn
    assert "AND fl.revenue IS NOT NULL" not in nace_fn


def test_nace_leg_orders_by_embedding_similarity_when_available():
    """When the target has an embedding, NACE peers are ordered by
    cosine distance to the target — not by enterprise_number ASC, which
    surfaced 1970s shell companies for low-revenue targets."""
    src = _read("backend/retrieval.py")
    assert "ce_emb.embedding <=> %s::vector" in src


def test_leg_b_limit_bumped_for_exhaustive_view():
    """The NACE leg fetch cap was raised from 80 to 300 so the exhaustive
    list has enough headroom after blend filtering."""
    src = _read("backend/retrieval.py")
    assert "LEG_B_LIMIT = 300" in src


def test_min_score_floor_relaxed_for_low_signal_targets():
    """Score floor was 15 — too tight for low-signal targets (no revenue,
    short bulk_summary) where candidates max out around 23 even with
    exact NACE + same city. Lowered to 5."""
    src = _read("backend/retrieval.py")
    assert "MIN_SCORE_FLOOR = 5" in src


def test_activity_overlap_filters_disabled():
    """For exhaustive-list mode, the activity-overlap floors that
    dropped 77% of NACE peers in PR #58's diagnosis are zeroed out."""
    src = _read("backend/retrieval.py")
    assert "NACE_ONLY_MIN_ACTIVITY_OVERLAP = 0.0" in src
    assert "ACTIVITY_FOCUS_MIN_ACTIVITY_OVERLAP = 0.0" in src


# ---------------------------------------------------------------------------
# Rerank wall-clock backstop (rerank.py + ai_routing.py)
# ---------------------------------------------------------------------------

def test_userpath_rerank_uses_wait_for_backstop():
    """asyncio.wait_for wraps each provider call so a wedged inner
    client (CPU-stuck tokenizer, broken socket) cannot hold the request
    open past the backstop."""
    src = _read("backend/rerank.py")
    assert "asyncio.wait_for(" in src
    assert "wall_backstop_s" in src


def test_wall_backstop_renamed_with_legacy_fallback():
    """WALL_TIMEOUT_S → WALL_BACKSTOP_S rename keeps a fallback to the
    old key so any existing env-var override keeps working."""
    src = _read("backend/rerank.py")
    assert 'SIMILAR_COMPANIES_ROUTING.get(\n            "WALL_BACKSTOP_S",' in src
    assert 'SIMILAR_COMPANIES_ROUTING.get("WALL_TIMEOUT_S",' in src


def test_userpath_fallback_is_haiku():
    """When the primary Ollama model times out, the find-similar user
    path jumps straight to Anthropic Haiku (no intermediate models),
    bounding total LLM latency."""
    routing = _read("backend/ai_routing.py")
    assert '"USERPATH_FALLBACK_MODEL": "anthropic/claude-haiku-4-5"' in routing


# ---------------------------------------------------------------------------
# DB pool stale-recovery (db.py)
# ---------------------------------------------------------------------------

def test_pool_pings_before_returning_connection():
    """get_connection() pings the connection before returning it so a
    stale slot left over from a PG restart gets detected and discarded
    instead of being handed to the next caller."""
    src = _read("backend/db.py")
    assert "_connection_is_alive" in src
    assert "SELECT 1" in src
