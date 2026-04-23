"""Regression checks for same-group exclusion in similar-company retrieval."""

import importlib.util
import os
import sys
import types


ROOT = os.path.join(os.path.dirname(__file__), "..")
BACKEND = os.path.join(ROOT, "backend")
RETRIEVAL_PATH = os.path.join(BACKEND, "retrieval.py")

if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)


def _normalize_name(name: str) -> str:
    text = " ".join(str(name or "").lower().split())
    for suffix in (" nv", " sa", " bv", " srl", " bvba", " sprl"):
        if text.endswith(suffix):
            text = text[: -len(suffix)]
    return text.strip()


def _clean_cbe(value) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if len(digits) not in (9, 10):
        return ""
    return digits.zfill(10)


def _load_retrieval_module(shared_owner_pct):
    db_stub = types.ModuleType("db")

    def fetch_all(query, params):
        sql = " ".join(str(query).split())
        if "FROM company_info ci" in sql and "LEFT JOIN company_enrichment ce" in sql:
            return [
                {
                    "enterprise_number": "0000000002",
                    "name": "PeerCo NV",
                    "city": "Antwerp",
                    "zipcode": "2000",
                    "nace_code": "46690",
                    "revenue": 950000.0,
                    "ebitda": 120000.0,
                    "fte_total": 18.0,
                    "fiscal_year": 2024,
                    "ebit": 100000.0,
                    "net_profit": 70000.0,
                    "equity": 150000.0,
                    "total_assets": 400000.0,
                    "personnel_costs": 250000.0,
                    "nace_desc": "Wholesale of other machinery",
                    "bulk_summary": {
                        "business_description": "Supplies industrial refrigeration systems to food processors.",
                        "products_services": ["industrial refrigeration systems"],
                        "customer_segments": ["food processors"],
                    },
                    "ai_insights": None,
                },
                {
                    "enterprise_number": "0000000003",
                    "name": "Independent Cooling NV",
                    "city": "Ghent",
                    "zipcode": "9000",
                    "nace_code": "46690",
                    "revenue": 980000.0,
                    "ebitda": 110000.0,
                    "fte_total": 19.0,
                    "fiscal_year": 2024,
                    "ebit": 95000.0,
                    "net_profit": 65000.0,
                    "equity": 140000.0,
                    "total_assets": 390000.0,
                    "personnel_costs": 245000.0,
                    "nace_desc": "Wholesale of other machinery",
                    "bulk_summary": {
                        "business_description": "Supplies industrial refrigeration systems to food processors.",
                        "products_services": ["industrial refrigeration systems"],
                        "customer_segments": ["food processors"],
                    },
                    "ai_insights": None,
                },
            ]
        if "FROM shareholder" in sql:
            return [
                {
                    "enterprise_number": "0000000001",
                    "identifier": "0000000010",
                    "name": "HoldCo NV",
                    "ownership_pct": shared_owner_pct,
                    "shareholder_type": "entity",
                },
                {
                    "enterprise_number": "0000000002",
                    "identifier": "0000000010",
                    "name": "HoldCo NV",
                    "ownership_pct": shared_owner_pct,
                    "shareholder_type": "entity",
                },
                {
                    "enterprise_number": "0000000003",
                    "identifier": "0000000020",
                    "name": "Other Group NV",
                    "ownership_pct": 100.0,
                    "shareholder_type": "entity",
                },
            ]
        if "FROM participating_interest" in sql:
            return []
        raise AssertionError(f"Unexpected SQL in test stub: {sql}")

    db_stub.fetch_all = fetch_all
    db_stub.fetch_one = lambda *args, **kwargs: None
    db_stub.normalize_name = _normalize_name
    sys.modules["db"] = db_stub

    utils_stub = types.ModuleType("utils")
    utils_stub.clean_cbe = _clean_cbe
    sys.modules["utils"] = utils_stub

    spec = importlib.util.spec_from_file_location("retrieval", RETRIEVAL_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _run_same_group_exclusion_case(shared_owner_pct):
    retrieval = _load_retrieval_module(shared_owner_pct)
    target = {
        "enterprise_number": "0000000001",
        "name": "TargetCo NV",
        "nace_code": "46690",
        "revenue": 1_000_000.0,
        "city": "Antwerp",
        "zipcode": "2000",
        "bulk_summary": {
            "business_description": "Supplies industrial refrigeration systems to food processors.",
            "products_services": ["industrial refrigeration systems"],
            "customer_segments": ["food processors"],
        },
        "ai_insights": None,
    }
    legs = {
        "embedding": [
            {"enterprise_number": "0000000002", "embedding_similarity": 0.92},
            {"enterprise_number": "0000000003", "embedding_similarity": 0.88},
        ],
        "nace": [
            {"enterprise_number": "0000000002", "nace_score": 1.0},
            {"enterprise_number": "0000000003", "nace_score": 1.0},
        ],
        "size_band": [],
    }

    ranked = retrieval.blend_candidates(legs, "activity", target)
    returned = [row["enterprise_number"] for row in ranked]

    assert "0000000002" not in returned
    assert returned == ["0000000003"]


def test_same_group_candidates_are_removed_before_ranking():
    _run_same_group_exclusion_case(100.0)


def test_shared_entity_shareholder_without_pct_is_still_excluded():
    _run_same_group_exclusion_case(None)


if __name__ == "__main__":
    test_same_group_candidates_are_removed_before_ranking()
    test_shared_entity_shareholder_without_pct_is_still_excluded()
    print("All similar-group-filter tests passed.")
