import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "migrations" / "2026-05-04_bitemporal_valid_from_stage_b.sql"


def _sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def test_stage_b_migration_keeps_later_rollout_stages_out():
    sql = _sql().lower()

    assert "valid_from_provenance" not in sql
    assert "alter column valid_from set not null" not in sql
    assert " set not null" not in sql


def test_stage_b_uses_staatsblad_effective_date_source():
    sql = _sql()

    assert "FROM staatsblad_event ev" in sql
    assert "COALESCE(ev.event_date, ev.pub_date) AS effective_date" in sql
    assert "_bt_vf_stage_b_pub_reference" in sql


def test_stage_b_valid_from_updates_are_null_only():
    sql = _sql()
    aliases = {
        "administrator": "a",
        "shareholder": "sh",
        "participating_interest": "pi",
        "affiliation": "af",
    }

    for table, alias in aliases.items():
        pattern = re.compile(
            rf"UPDATE {table} {alias}\b.*?SET valid_from\b.*?"
            rf"WHERE .*?{alias}\.valid_from IS NULL",
            re.DOTALL,
        )
        assert pattern.search(sql), f"{table} valid_from update is not NULL-only"


def test_stage_b_valid_to_updates_are_null_only_and_post_nbb():
    sql = _sql()
    aliases = {
        "administrator": "a",
        "shareholder": "sh",
        "participating_interest": "pi",
        "affiliation": "af",
    }

    for table, alias in aliases.items():
        pattern = re.compile(
            rf"UPDATE {table} {alias}\b.*?SET valid_to\b.*?"
            rf"WHERE .*?{alias}\.valid_to IS NULL",
            re.DOTALL,
        )
        assert pattern.search(sql), f"{table} valid_to update is not NULL-only"

    assert "ev.effective_date > a.source_deposit_date" in sql
    assert "ev.effective_date > sh.source_deposit_date" in sql
    assert "ev.effective_date > pi.source_deposit_date" in sql
    assert "ev.effective_date > af.source_deposit_date" in sql
