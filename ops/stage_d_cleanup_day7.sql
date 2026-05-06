-- Stage D cleanup - day+7 manual apply.
-- This file is INTENTIONALLY OUTSIDE migrations/ so scripts/migrate.py
-- does not pick it up. Apply via: bash ops/_apply_stage_d_cleanup.sh
-- Apply on or after: <apply_date+7d, filled in by Stage 5 operator>
-- Direct psql -f is blocked unless the helper passes stage_d_cleanup_confirmed.

\if :{?stage_d_cleanup_confirmed}
\else
\echo 'Refusing Stage D cleanup: run via bash ops/_apply_stage_d_cleanup.sh after day +7.'
\quit 3
\endif

DROP TABLE IF EXISTS _bt_vf_stage_d_backup_administrator;
DROP TABLE IF EXISTS _bt_vf_stage_d_backup_shareholder;
DROP TABLE IF EXISTS _bt_vf_stage_d_backup_participating_interest;
DROP TABLE IF EXISTS _bt_vf_stage_d_backup_affiliation;
