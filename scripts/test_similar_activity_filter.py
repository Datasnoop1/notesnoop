"""Regression check that same-NACE but unrelated businesses are filtered out."""

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


def _load_retrieval_module():
    db_stub = types.ModuleType("db")

    def fetch_all(query, params):
        sql = " ".join(str(query).split())
        if "FROM company_info ci" in sql and "LEFT JOIN company_enrichment ce" in sql:
            return [
                {
                    "enterprise_number": "0000000002",
                    "name": "Related Cooling NV",
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
                    "name": "Unrelated Cleaning NV",
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
                        "business_description": "Provides office cleaning and janitorial contracts for commercial buildings.",
                        "products_services": ["office cleaning", "janitorial contracts"],
                        "customer_segments": ["commercial buildings"],
                    },
                    "ai_insights": None,
                },
            ]
        if "FROM shareholder" in sql or "FROM participating_interest" in sql:
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


def test_same_nace_without_real_business_overlap_is_removed():
    retrieval = _load_retrieval_module()
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
        "embedding": [],
        "nace": [
            {"enterprise_number": "0000000002", "nace_score": 1.0},
            {"enterprise_number": "0000000003", "nace_score": 1.0},
        ],
        "size_band": [],
    }

    ranked = retrieval.blend_candidates(legs, "activity", target)
    returned = [row["enterprise_number"] for row in ranked]

    assert "0000000002" in returned
    assert "0000000003" not in returned


if __name__ == "__main__":
    test_same_nace_without_real_business_overlap_is_removed()
    print("All similar-activity-filter tests passed.")
