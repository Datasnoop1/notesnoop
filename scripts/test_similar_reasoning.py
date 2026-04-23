"""Regression checks for structured similar-company reasons."""

import importlib.util
import os
import sys
import types


ROOT = os.path.join(os.path.dirname(__file__), "..")
SIMILAR_PATH = os.path.join(ROOT, "backend", "routers", "companies", "similar.py")


def _load_similar_module():
    fastapi_stub = types.ModuleType("fastapi")

    class _Router:
        def get(self, *args, **kwargs):
            def decorator(fn):
                return fn

            return decorator

    class _HTTPException(Exception):
        def __init__(self, status_code=None, detail=None):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

    fastapi_stub.APIRouter = lambda *args, **kwargs: _Router()
    fastapi_stub.Depends = lambda dependency=None: dependency
    fastapi_stub.HTTPException = _HTTPException
    fastapi_stub.Query = lambda default=None, **kwargs: default
    sys.modules["fastapi"] = fastapi_stub

    db_stub = types.ModuleType("db")
    db_stub.fetch_all = lambda *args, **kwargs: []
    db_stub.fetch_one = lambda *args, **kwargs: None
    db_stub.execute = lambda *args, **kwargs: None
    sys.modules["db"] = db_stub

    auth_stub = types.ModuleType("auth")
    auth_stub.optional_user = None
    sys.modules["auth"] = auth_stub

    ai_routing_stub = types.ModuleType("ai_routing")
    ai_routing_stub.SIMILAR_COMPANIES_ROUTING = {}
    ai_routing_stub.estimate_cost_usd = lambda *args, **kwargs: 0.0
    ai_routing_stub.get_tier_config = lambda *args, **kwargs: {"model": "anthropic/claude-haiku-4-5"}
    ai_routing_stub.select_tier = lambda cheap_mode=False: "DEFAULT"
    sys.modules["ai_routing"] = ai_routing_stub

    retrieval_stub = types.ModuleType("retrieval")
    retrieval_stub.LLM_INPUT_SET_SIZE = 25
    retrieval_stub.blend_candidates = lambda *args, **kwargs: []
    retrieval_stub.leg_needs_fallback = lambda *args, **kwargs: False
    retrieval_stub.retrieve_by_embedding = lambda *args, **kwargs: []
    retrieval_stub.retrieve_by_nace = lambda *args, **kwargs: []
    retrieval_stub.retrieve_by_size_band = lambda *args, **kwargs: []
    sys.modules["retrieval"] = retrieval_stub

    rerank_stub = types.ModuleType("rerank")
    rerank_stub.MIN_CANDIDATES_FOR_LLM = 5
    rerank_stub.build_target_insight_block = lambda *args, **kwargs: ""
    rerank_stub.call_rerank_llm = lambda *args, **kwargs: None
    rerank_stub.render_prompt = lambda *args, **kwargs: ""
    sys.modules["rerank"] = rerank_stub

    similar_cache_stub = types.ModuleType("similar_cache")
    similar_cache_stub.compute_content_hash = lambda *args, **kwargs: "hash"
    similar_cache_stub.ensure_similar_cache_schema = lambda *args, **kwargs: None
    sys.modules["similar_cache"] = similar_cache_stub

    utils_stub = types.ModuleType("utils")
    utils_stub.clean_cbe = lambda cbe: cbe
    sys.modules["utils"] = utils_stub

    routers_pkg = types.ModuleType("routers")
    routers_pkg.__path__ = []
    companies_pkg = types.ModuleType("routers.companies")
    companies_pkg.__path__ = []
    helpers_stub = types.ModuleType("routers.companies._helpers")
    helpers_stub._serialize_row = lambda row: dict(row)
    sys.modules["routers"] = routers_pkg
    sys.modules["routers.companies"] = companies_pkg
    sys.modules["routers.companies._helpers"] = helpers_stub

    spec = importlib.util.spec_from_file_location("routers.companies.similar", SIMILAR_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


_similar = _load_similar_module()
_extract_reason_sections = _similar._extract_reason_sections
_normalize_reason = _similar._normalize_reason


def test_period_delimited_reason_normalizes_to_structured_format():
    fallback = (
        "Activity: Packaging machinery for food producers | "
        "Size: Comparable EUR10-20M manufacturer scale | "
        "Geography: Different region, secondary factor"
    )
    raw = (
        "Activity: Packaging machinery for food producers. "
        "Size: Similar EUR10-20M manufacturer scale. "
        "Geography: Different region, secondary factor."
    )

    normalized = _normalize_reason(raw, fallback)
    assert normalized == (
        "Activity: Packaging machinery for food producers | "
        "Size: Similar EUR10-20M manufacturer scale | "
        "Geography: Different region, secondary factor"
    )
    assert _extract_reason_sections(normalized) == {
        "activity": "Packaging machinery for food producers",
        "size": "Similar EUR10-20M manufacturer scale",
        "geography": "Different region, secondary factor",
    }


def test_generic_reason_backfills_missing_sections():
    fallback = (
        "Activity: Industrial fasteners for construction distributors | "
        "Size: Revenue is in a comparable range; FTE around 42 | "
        "Geography: Same province area: Antwerp"
    )
    raw = "Industrial fasteners for construction distributors"

    normalized = _normalize_reason(raw, fallback)
    assert normalized == (
        "Activity: Industrial fasteners for construction distributors | "
        "Size: Revenue is in a comparable range; FTE around 42 | "
        "Geography: Same province area: Antwerp"
    )
    assert _extract_reason_sections(normalized)["size"] == (
        "Revenue is in a comparable range; FTE around 42"
    )


if __name__ == "__main__":
    test_period_delimited_reason_normalizes_to_structured_format()
    test_generic_reason_backfills_missing_sections()
    print("All similar-reasoning tests passed.")
