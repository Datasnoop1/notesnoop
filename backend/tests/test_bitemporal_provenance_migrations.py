import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COLUMNS_MIGRATION = ROOT / "migrations" / "2026-05-04_bitemporal_provenance_columns.sql"
BACKFILL_MIGRATION = ROOT / "migrations" / "2026-05-04_bitemporal_provenance_columns_backfill.sql"


def _columns_sql() -> str:
    return COLUMNS_MIGRATION.read_text(encoding="utf-8")


def _backfill_sql() -> str:
    return BACKFILL_MIGRATION.read_text(encoding="utf-8")


def test_stage_c_columns_are_nullable_metadata_only():
    sql = _columns_sql()
    lower = sql.lower()

    for table in ("administrator", "shareholder", "participating_interest", "affiliation"):
        assert f"ALTER TABLE {table}" in sql

    assert "valid_from_provenance TEXT" in sql
    assert "valid_to_provenance TEXT" in sql
    assert " default " not in lower
    assert " set not null" not in lower


def test_stage_c_backfill_keeps_rollout_boundaries():
    sql = _backfill_sql()
    lower = sql.lower()

    assert "set valid_from =" not in lower
    assert "set valid_to =" not in lower
    assert "alter column" not in lower
    assert "set not null" not in lower
    assert "drop table" not in lower
    assert "fallback_enterprise_start" not in lower


def test_stage_c_backfill_has_expected_provenance_vocabulary():
    sql = _backfill_sql()

    for value in (
        "nbb_mandate_start",
        "nbb_filing_earliest",
        "staatsblad_event_date",
        "staatsblad_pub_date",
        "staatsblad_supersession",
        "nbb_loader_direct",
        "staatsblad_consumer_direct",
        "unknown",
    ):
        assert value in sql


def test_stage_c_backfill_uses_stage_a_and_stage_b_evidence():
    sql = _backfill_sql()

    assert "_bt_vf_stage_a_backup_admin" in sql
    assert "_bt_vf_stage_b_backup_administrator" in sql
    assert "COALESCE(ev.event_date, ev.pub_date) AS effective_date" in sql
    assert "WHEN ev.event_date IS NOT NULL THEN 'staatsblad_event_date'" in sql
    assert "ELSE 'staatsblad_pub_date'" in sql
    assert "ev.enterprise_number = af.via_enterprise_number" in sql


def test_stage_c_backfill_updates_are_provenance_null_only():
    sql = _backfill_sql()
    updates = re.findall(
        r"\bUPDATE\s+(administrator|shareholder|participating_interest|affiliation)\s+\w+\b.*?;",
        sql,
        flags=re.IGNORECASE | re.DOTALL,
    )
    assert updates

    update_blocks = re.finditer(
        r"\bUPDATE\s+(?:administrator|shareholder|participating_interest|affiliation)\s+\w+\b.*?;",
        sql,
        flags=re.IGNORECASE | re.DOTALL,
    )
    for match in update_blocks:
        block = match.group(0).lower()
        assert (
            "valid_from_provenance is null" in block
            or "valid_to_provenance is null" in block
        ), block[:240]
