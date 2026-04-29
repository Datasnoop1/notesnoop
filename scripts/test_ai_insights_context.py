from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.ai_client import _annotate_key_management, _fetch_company_context


def test_fetch_company_context_uses_enterprise_fallback() -> None:
    seen = {}

    def fake_fetch_one(query, params):
        seen["query"] = query
        seen["params"] = params
        return {
            "enterprise_number": "0403091121",
            "name": "Full Clean Centre",
            "city": None,
            "zipcode": "1702",
            "street": "Noordkustlaan",
            "house_number": "16C",
            "sector": None,
            "revenue": 5_000_000,
            "ebitda": 400_000,
            "fte_total": 30,
            "fiscal_year": 2024,
            "nace_code": None,
        }

    company = _fetch_company_context(fake_fetch_one, "0403091121")

    assert company is not None
    assert "FROM enterprise e" in seen["query"]
    assert seen["params"] == ("0403091121",)
    assert company["name"] == "Full Clean Centre"
    assert company["city"] == "Belgium"
    assert company["street"] == "Noordkustlaan"
    assert company["sector"] == ""
    assert company["revenue"] == 5_000_000


def test_fetch_company_context_returns_none_when_company_is_missing() -> None:
    def fake_fetch_one(query, params):
        return None

    assert _fetch_company_context(fake_fetch_one, "0000000000") is None


def test_key_management_annotation_treats_future_mandates_as_active() -> None:
    insights = {
        "key_management": [
            {"name": "Alice Example"},
            {"name": "Bob Future"},
            {"name": "Cara Past"},
            {"name": "Dana Website"},
        ]
    }

    def fake_fetch_all(query, params):
        assert params == ("0403091121",)
        return [
            {"name": "Alice Example", "mandate_end": None},
            {"name": "Bob Future", "mandate_end": "2999-12-31"},
            {"name": "Cara Past", "mandate_end": "2020-01-01"},
        ]

    _annotate_key_management(insights, fake_fetch_all, "0403091121")

    statuses = {
        item["name"]: item["mandate_status"]
        for item in insights["key_management"]
    }
    assert statuses == {
        "Alice Example": "kbo_active",
        "Bob Future": "kbo_active",
        "Cara Past": "kbo_resigned",
        "Dana Website": "website_only",
    }


if __name__ == "__main__":
    test_fetch_company_context_uses_enterprise_fallback()
    test_fetch_company_context_returns_none_when_company_is_missing()
    test_key_management_annotation_treats_future_mandates_as_active()
    print("ok")
