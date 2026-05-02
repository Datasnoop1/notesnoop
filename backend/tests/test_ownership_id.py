import os
import sys
from pathlib import Path


os.environ.setdefault("SUPABASE_HS256_FALLBACK", "1")
os.environ.setdefault("ACTIVITY_LOG_IP_SALT", "test-salt")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import feature_flags  # noqa: E402
from routers.companies import structure  # noqa: E402
from ownership_id import (  # noqa: E402
    classify_nbb_owner,
    clean_cbe,
    external_parent_id,
    person_parent,
    unknown_parent_id,
)


def test_ownership_graph_flag_defaults_off(monkeypatch):
    monkeypatch.delenv("OWNERSHIP_GRAPH_READ_ENABLED", raising=False)

    assert feature_flags.ownership_graph_read_enabled() is False


def test_ownership_graph_flag_reads_environment_each_call(monkeypatch):
    monkeypatch.setenv("OWNERSHIP_GRAPH_READ_ENABLED", "false")
    assert feature_flags.ownership_graph_read_enabled() is False

    monkeypatch.setenv("OWNERSHIP_GRAPH_READ_ENABLED", "true")
    assert feature_flags.ownership_graph_read_enabled() is True


def test_clean_cbe_accepts_dotted_belgian_number():
    assert clean_cbe("0403.170.701") == "0403170701"


def test_external_parent_id_uses_scheme_value_convention():
    assert external_parent_id("lei", " 5493001kjtiigc8y1r12 ") == "LEI:5493001KJTIIGC8Y1R12"


def test_unknown_parent_id_is_stable_and_country_scoped():
    belgian = unknown_parent_id("Acme Holding NV", "BE")
    dutch = unknown_parent_id("Acme Holding NV", "NL")

    assert belgian.startswith("unknown:")
    assert len(belgian) == len("unknown:") + 16
    assert unknown_parent_id("ACME HOLDING", "BE") == belgian
    assert dutch != belgian


def test_classify_nbb_owner_prefers_cbe_over_external_identifier():
    parent = classify_nbb_owner(name="Example Parent", identifier="0403.170.701")

    assert parent.parent_kind == "company"
    assert parent.parent_id == "0403170701"
    assert parent.parent_identifier_scheme == "CBE"


def test_person_parent_requires_uuid_shape():
    parent = person_parent("11111111-2222-3333-4444-555555555555", "Jane Doe")

    assert parent.parent_kind == "person"
    assert parent.parent_identifier_scheme == "UUID"


def test_classify_name_only_owner_uses_unknown_parent():
    parent = classify_nbb_owner(name="Name Only Holder")

    assert parent.parent_kind == "unknown"
    assert parent.parent_identifier_scheme is None
    assert parent.parent_id.startswith("unknown:")


def test_ownership_graph_direct_handler_coerces_query_default(monkeypatch):
    monkeypatch.setenv("OWNERSHIP_GRAPH_READ_ENABLED", "true")
    monkeypatch.setattr(
        structure,
        "_fetch_ownership_graph_structure",
        lambda _cbe: ([{"name": "Holder"}], [], []),
    )
    monkeypatch.setattr(
        structure,
        "fetch_all",
        lambda _sql, params=None: [{"depth": params[1]}],
    )

    import asyncio

    payload = asyncio.run(structure.get_company_ownership_graph("0403170701"))

    assert payload["ubo_walk"] == [{"depth": 6}]
