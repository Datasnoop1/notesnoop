import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "migrations" / "2026-05-05_bitemporal_valid_from_stage_d.sql"
ROLLBACK = ROOT / "migrations" / "2026-05-05_bitemporal_valid_from_stage_d_rollback.sql"
CLEANUP_SQL = ROOT / "ops" / "stage_d_cleanup_day7.sql"
CLEANUP_SH = ROOT / "ops" / "_apply_stage_d_cleanup.sh"
PSQL_HELPER = ROOT / "ops" / "_psql_prod_file.sh"
RUNBOOK = ROOT / "docs" / "bitemporal-stage-d-implementation-runbook.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_stage_d_forward_migration_headers_and_session_notes():
    sql = _read(MIGRATION)

    assert "-- @migration: tx" in sql
    assert "-- @migration: lock_timeout=5s" in sql
    assert "-- @migration: statement_timeout=600s" in sql
    assert "same psql session" in sql
    assert "AccessExclusive" in sql
    assert "pg_stat_activity" in sql


def test_stage_d_parser_accepts_two_formats_and_bounds_dates():
    sql = _read(MIGRATION)

    assert "CREATE OR REPLACE FUNCTION pg_temp._bt_vf_stage_d_try_date(raw TEXT)" in sql
    assert "^[0-9]{4}-[0-9]{2}-[0-9]{2}$" in sql
    assert "^[0-9]{2}/[0-9]{2}/[0-9]{4}$" in sql
    assert "parsed < DATE '1830-01-01' OR parsed > CURRENT_DATE" in sql


def test_stage_d_backup_tables_capture_expected_keys_and_backout_columns():
    sql = _read(MIGRATION)

    for table in (
        "administrator",
        "shareholder",
        "participating_interest",
        "affiliation",
    ):
        assert f"CREATE TABLE _bt_vf_stage_d_backup_{table}" in sql

    affiliation_block = re.search(
        r"CREATE TABLE _bt_vf_stage_d_backup_affiliation AS(?P<body>.*?)FROM affiliation af",
        sql,
        flags=re.DOTALL,
    )
    assert affiliation_block
    body = affiliation_block.group("body")
    assert "af.person_name" in body
    assert "af.enterprise_number" in body
    assert "af.via_enterprise_number" in body
    assert "af.affiliation_type" in body
    assert "af.deposit_key" not in body
    assert "af.via_deposit_key" in body

    for column in (
        "valid_from",
        "valid_to",
        "valid_from_provenance",
        "valid_to_provenance",
        "enterprise_start_date_raw",
        "enterprise_start_date",
        "fallback_filing_deposit_date",
        "fallback_recorded_from_date",
        "fallback_valid_from",
        "fallback_provenance",
        "source_date_capped",
        "backed_up_at",
    ):
        assert column in sql


def test_stage_d_updates_fill_only_null_valid_from_with_ordered_fallbacks():
    sql = _read(MIGRATION)
    aliases = {
        "administrator": "a",
        "shareholder": "sh",
        "participating_interest": "pi",
        "affiliation": "af",
    }

    assert "fallback_enterprise_start" in sql
    assert "LEAST(b.enterprise_start_date, a.source_deposit_date)" in sql
    assert "LEAST(b.enterprise_start_date, sh.source_deposit_date)" in sql
    assert "LEAST(b.enterprise_start_date, pi.source_deposit_date)" in sql
    assert "LEAST(b.enterprise_start_date, af.source_deposit_date)" in sql
    assert "fallback_filing_deposit" in sql
    assert "fallback_unknown_start" in sql
    assert "a.deposit_key IS NOT DISTINCT FROM b.deposit_key" in sql
    assert "sh.deposit_key IS NOT DISTINCT FROM b.deposit_key" in sql
    assert "pi.deposit_key IS NOT DISTINCT FROM b.deposit_key" in sql
    assert "pg_temp._bt_vf_stage_d_try_date(fd.deposit_date::text) IS NOT NULL" in sql
    assert "SET valid_from = b.fallback_valid_from" in sql
    assert "b.fallback_provenance = 'fallback_filing_deposit'" in sql
    assert "b.fallback_valid_from = b.fallback_filing_deposit_date" in sql
    assert "b.fallback_provenance = 'fallback_unknown_start'" in sql
    assert "b.fallback_valid_from = b.fallback_recorded_from_date" in sql

    enterprise_arm = sql.index("UPDATE affiliation af")
    filing_arm = sql.index("valid_from_provenance = 'fallback_filing_deposit'")
    unknown_arm = sql.index("valid_from_provenance = 'fallback_unknown_start'")
    residual_gate = sql.index("Stage D abort: residual NULL valid_from rows remain")
    assert enterprise_arm < filing_arm < unknown_arm < residual_gate

    for table, alias in aliases.items():
        pattern = re.compile(
            rf"UPDATE {table} {alias}\b.*?SET valid_from\b.*?"
            rf"WHERE {alias}\.valid_from IS NULL",
            flags=re.DOTALL,
        )
        assert pattern.search(sql), f"{table} fallback update is not NULL-only"


def test_stage_d_residual_gates_and_not_null_constraints_only_valid_from():
    sql = _read(MIGRATION)
    lower = sql.lower()

    assert "Stage D abort: residual NULL valid_from rows remain" in sql
    assert "VALIDATE CONSTRAINT administrator_valid_from_not_null" in sql
    assert "VALIDATE CONSTRAINT shareholder_valid_from_not_null" in sql
    assert "VALIDATE CONSTRAINT participating_interest_valid_from_not_null" in sql
    assert "VALIDATE CONSTRAINT affiliation_valid_from_not_null" in sql
    assert "alter column valid_from set not null" in lower
    assert "alter column valid_to set not null" not in lower
    assert "backup tables already exist" in sql


def test_stage_d_rewrites_governance_views_without_valid_from_null_branch():
    sql = _read(MIGRATION)

    view_section = sql.split("CREATE OR REPLACE VIEW administrator_current AS", 1)[1]
    assert "(valid_from IS NULL OR valid_from <=" not in view_section
    assert "WHERE valid_from <= CURRENT_DATE" in view_section
    assert "WHERE valid_from <= valid_at" in view_section
    assert "(valid_to IS NULL OR valid_to > CURRENT_DATE)" in view_section
    assert "(valid_to IS NULL OR valid_to > valid_at)" in view_section


def test_stage_d_comments_extend_stage_c_vocabulary_without_renaming():
    sql = _read(MIGRATION)

    for value in (
        "nbb_mandate_start",
        "nbb_filing_earliest",
        "staatsblad_event_date",
        "staatsblad_pub_date",
        "nbb_loader_direct",
        "staatsblad_consumer_direct",
        "fallback_enterprise_start",
        "fallback_filing_deposit",
        "fallback_unknown_start",
        "unknown",
    ):
        assert value in sql


def test_stage_d_rollback_restores_constraints_data_views_and_comments():
    sql = _read(ROLLBACK)
    lower = sql.lower()

    assert re.search(r"^BEGIN;\s+SET LOCAL lock_timeout = '5s';\s+SET LOCAL statement_timeout = '600s';", sql, re.MULTILINE)
    assert sql.rstrip().endswith("COMMIT;")
    assert "drop constraint if exists administrator_valid_from_not_null" in lower
    assert "alter column valid_from drop not null" in lower
    assert "(valid_from IS NULL OR valid_from <= CURRENT_DATE)" in sql
    assert "(valid_from IS NULL OR valid_from <= valid_at)" in sql
    assert "FROM _bt_vf_stage_d_backup_administrator b" in sql
    assert "FROM _bt_vf_stage_d_backup_shareholder b" in sql
    assert "FROM _bt_vf_stage_d_backup_participating_interest b" in sql
    assert "FROM _bt_vf_stage_d_backup_affiliation b" in sql
    assert "fallback_enterprise_start" in sql
    assert "fallback_filing_deposit" in sql
    assert "fallback_unknown_start" in sql
    assert "af.valid_from_provenance = b.fallback_provenance" in sql
    assert "a.deposit_key IS NOT DISTINCT FROM b.deposit_key" in sql
    assert "sh.deposit_key IS NOT DISTINCT FROM b.deposit_key" in sql
    assert "pi.deposit_key IS NOT DISTINCT FROM b.deposit_key" in sql

    comment_section = sql.split("COMMENT ON COLUMN administrator.valid_from_provenance", 1)[1]
    assert "fallback_enterprise_start" not in comment_section
    assert "fallback_filing_deposit" not in comment_section
    assert "fallback_unknown_start" not in comment_section


def test_stage_d_cleanup_is_outside_migration_runner_scope_and_manual_day7():
    assert CLEANUP_SQL.exists()
    assert CLEANUP_SH.exists()
    assert PSQL_HELPER.exists()
    assert CLEANUP_SQL.parent.name == "ops"
    assert CLEANUP_SH.parent.name == "ops"
    assert PSQL_HELPER.parent.name == "ops"

    cleanup_sql = _read(CLEANUP_SQL)
    cleanup_sh = _read(CLEANUP_SH)
    psql_helper = _read(PSQL_HELPER)
    runbook = _read(RUNBOOK)

    assert "INTENTIONALLY OUTSIDE migrations/" in cleanup_sql
    assert "Apply on or after: <apply_date+7d" in cleanup_sql
    assert r"\if :{?stage_d_cleanup_confirmed}" in cleanup_sql
    assert r"\quit 3" in cleanup_sql
    assert "DROP TABLE IF EXISTS _bt_vf_stage_d_backup_administrator" in cleanup_sql
    assert "STAGE_D_CLEANUP_CONFIRM" in cleanup_sh
    assert "DROP_STAGE_D_BACKUPS_AFTER_DAY7" in cleanup_sh
    assert "STAGE_D_APPLY_DATE" in cleanup_sh
    assert "date -u -d" in cleanup_sh
    assert 'exec ops/_psql_prod_file.sh -v ON_ERROR_STOP=1 -v stage_d_cleanup_confirmed=1 -f ops/stage_d_cleanup_day7.sql' in cleanup_sh
    assert 'psql "$@"' in psql_helper
    assert 'psql "$MIGRATE_PROD_DATABASE_URL"' not in cleanup_sh
    assert 'psql "$MIGRATE_PROD_DATABASE_URL"' not in runbook
    assert "PGPASSFILE" in psql_helper
    assert 'env -i PATH="${PATH:-/usr/bin:/bin}" HOME="${HOME:-/root}" python3' in psql_helper
    assert "unset MIGRATE_PROD_DATABASE_URL PROD_DATABASE_URL HETZNER_PG_URL DATABASE_URL" in psql_helper
    assert "do not run cleanup before day +7" in runbook.lower()
    assert "STAGE_D_APPLY_DATE=YYYY-MM-DD STAGE_D_CLEANUP_CONFIRM=DROP_STAGE_D_BACKUPS_AFTER_DAY7 bash ops/_apply_stage_d_cleanup.sh" in runbook


def test_stage_d_runbook_requires_dry_run_and_transactional_rollback():
    runbook = _read(RUNBOOK)

    assert "python3 scripts/migrate.py dry-run --target=prod" in runbook
    assert "exactly one pending migration" in runbook
    assert "2026-05-05_bitemporal_valid_from_stage_d.sql" in runbook
    assert "ops/_psql_prod_file.sh -v ON_ERROR_STOP=1 -f migrations/2026-05-05_bitemporal_valid_from_stage_d_rollback.sql" in runbook
    assert "The rollback file is self-transactional" in runbook
