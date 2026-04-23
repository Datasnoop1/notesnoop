"""Regression checks for factual similarity-profile helpers."""

import os
import sys


ROOT = os.path.join(os.path.dirname(__file__), "..")
BACKEND = os.path.join(ROOT, "backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from similarity_profile import (  # noqa: E402
    build_similarity_profile,
    compute_activity_overlap_score,
    describe_activity_overlap,
)


def test_bulk_summary_is_preferred_over_ai_insights():
    profile = build_similarity_profile(
        {
            "business_description": "Distributes industrial refrigeration systems to food processors.",
            "products_services": ["industrial refrigeration systems"],
            "customer_segments": ["food processors"],
        },
        {
            "business_description": "Part of a wider holding group with several subsidiaries.",
            "products": ["holding activities"],
            "customers": [],
            "market_position": "",
        },
    )
    assert profile["source"] == "bulk"
    assert profile["products"] == ["industrial refrigeration systems"]
    assert "holding" not in profile["business_description"].lower()


def test_activity_overlap_uses_specific_product_and_customer_signals():
    target = build_similarity_profile(
        {
            "business_description": "Supplies industrial refrigeration systems and cooling controls.",
            "products_services": ["industrial refrigeration systems", "cooling controls"],
            "customer_segments": ["food processors", "cold storage operators"],
        },
        None,
    )
    candidate = build_similarity_profile(
        {
            "business_description": "Installs industrial refrigeration systems for food processors in Belgium.",
            "products_services": ["industrial refrigeration systems"],
            "customer_segments": ["food processors"],
        },
        None,
    )
    unrelated = build_similarity_profile(
        {
            "business_description": "Runs office cleaning and janitorial contracts.",
            "products_services": ["office cleaning"],
            "customer_segments": ["office landlords"],
        },
        None,
    )

    assert compute_activity_overlap_score(target, candidate) > 0.25
    assert compute_activity_overlap_score(target, unrelated) == 0.0
    assert describe_activity_overlap(target, candidate) == "industrial refrigeration systems"


def test_activity_anchor_prefers_specific_business_phrase_over_generic_customer():
    target = build_similarity_profile(
        {
            "business_description": "Provides temporary staffing and permanent recruitment for industrial employers.",
            "products_services": ["temporary staffing", "permanent recruitment"],
            "customer_segments": ["job seekers", "employers"],
        },
        None,
    )
    candidate = build_similarity_profile(
        {
            "business_description": "Offers temporary staffing and recruitment services for logistics and industrial employers.",
            "products_services": ["temporary staffing", "recruitment services"],
            "customer_segments": ["job seekers", "corporate clients"],
        },
        None,
    )

    assert describe_activity_overlap(target, candidate) == "temporary staffing"


if __name__ == "__main__":
    test_bulk_summary_is_preferred_over_ai_insights()
    test_activity_overlap_uses_specific_product_and_customer_signals()
    test_activity_anchor_prefers_specific_business_phrase_over_generic_customer()
    print("All similarity-profile tests passed.")
