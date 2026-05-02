from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "migrations" / "2026-05-02_ownership_graph.sql"


def _migration_sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def test_migration_excludes_apache_age():
    sql = _migration_sql().lower()

    assert "create extension if not exists age" not in sql
    assert " ag_catalog" not in sql


def test_migration_enforces_external_and_unknown_parent_id_conventions():
    sql = _migration_sql()

    assert "parent_id = parent_identifier_scheme || ':' || parent_identifier_value" in sql
    assert "parent_id ~ '^unknown:[0-9a-f]{16}$'" in sql
    assert "parent_identifier_scheme IS NULL" in sql


def test_migration_keeps_source_action_sequence_unique():
    sql = _migration_sql()

    assert "source_action_seq          INT NOT NULL DEFAULT 0" in sql
    assert "UNIQUE (source_table, source_pk, source_action_seq)" in sql


def test_current_and_as_of_views_accept_null_valid_from():
    sql = _migration_sql()

    assert "WHERE (valid_from IS NULL OR valid_from <= CURRENT_DATE)" in sql
    assert "WHERE (oe.valid_from IS NULL OR oe.valid_from <= target_date)" in sql


def test_ubo_helper_is_recursive_and_depth_capped():
    sql = _migration_sql()

    assert "WITH RECURSIVE walk AS" in sql
    assert "ARRAY['company:' || root_child_id" in sql
    assert "walk.depth < GREATEST(1, LEAST(max_depth, 12))" in sql
    assert "NOT walk.cycle" in sql
