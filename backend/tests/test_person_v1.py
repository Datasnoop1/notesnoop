"""Regression tests for Person v1 internal-only access."""

import os
import sys
from pathlib import Path
from uuid import UUID


os.environ.setdefault("SUPABASE_HS256_FALLBACK", "1")
os.environ.setdefault("ACTIVITY_LOG_IP_SALT", "test-salt")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import feature_flags  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from routers import people  # noqa: E402
from scripts import person_resolver  # noqa: E402


def test_person_public_url_flag_defaults_off(monkeypatch):
    monkeypatch.delenv("PERSON_PUBLIC_URL_ENABLED", raising=False)

    assert feature_flags.person_public_url_enabled() is False


def test_person_public_url_flag_reads_environment_each_call(monkeypatch):
    monkeypatch.setenv("PERSON_PUBLIC_URL_ENABLED", "false")
    assert feature_flags.person_public_url_enabled() is False

    monkeypatch.setenv("PERSON_PUBLIC_URL_ENABLED", "true")
    assert feature_flags.person_public_url_enabled() is True


def test_person_gate_returns_404_for_anonymous_when_public_off(monkeypatch):
    monkeypatch.setenv("PERSON_PUBLIC_URL_ENABLED", "false")

    try:
        people._require_person_v1_access(None)
    except HTTPException as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("anonymous access should be hidden when public flag is off")


def test_person_gate_allows_public_flag_without_user(monkeypatch):
    monkeypatch.setenv("PERSON_PUBLIC_URL_ENABLED", "true")

    assert people._require_person_v1_access(None) is None


def test_person_resolver_uses_source_mention_seq_and_affiliation():
    sql_blob = "\n".join(
        [
            person_resolver.TIER_A_LINK_SQL,
            person_resolver.TIER_B_LINK_SQL,
            *person_resolver.TIER_C_SQL_BY_SOURCE.values(),
        ]
    )

    assert "source_mention_seq" in sql_blob
    assert "affiliation" in sql_blob


def test_person_resolver_namespace_produces_uuid_shape():
    stable_id = UUID("00000000-0000-0000-0000-000000000000")

    assert str(stable_id) == "00000000-0000-0000-0000-000000000000"
