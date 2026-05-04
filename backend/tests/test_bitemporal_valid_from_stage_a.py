import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "migrations" / "2026-05-04_bitemporal_valid_from_stage_a.sql"


def _sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def test_stage_a_migration_keeps_later_rollout_stages_out():
    sql = _sql().lower()

    assert "staatsblad_event" not in sql
    assert "valid_from_provenance" not in sql
    assert "alter column valid_from set not null" not in sql


def test_stage_a_updates_only_null_valid_from_rows():
    sql = _sql()
    aliases = {
        "administrator": "a",
        "shareholder": "sh",
        "participating_interest": "pi",
        "affiliation": "af",
    }

    for table, alias in aliases.items():
        pattern = re.compile(
            rf"UPDATE {table} {alias}\b.*?WHERE .*?{alias}\.valid_from IS NULL",
            re.DOTALL,
        )
        assert pattern.search(sql), f"{table} update is not scoped to NULL valid_from"


def test_stage_a_admin_uses_earliest_mentions_before_filing_date_fallback():
    sql = _sql()

    assert "_bt_vf_stage_a_admin_filing_refs" in sql
    assert "earliest_mandate_start" in sql
    assert "COALESCE(c.earliest_mandate_start, c.earliest_filing_ref)" in sql
    assert "ELSE fd.deposit_date" not in sql
