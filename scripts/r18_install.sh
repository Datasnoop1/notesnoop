#!/bin/bash
# Stage R18 Phase 2a artefacts on the host (idempotent). Copies systemd
# units into /etc/systemd/system/, marks scripts executable, and verifies
# prerequisites — but DOES NOT enable or start anything. Activation is
# Gate B and is performed by the operator running:
#
#   systemctl enable --now leadpeek-backup.timer
#   bash /opt/leadpeek/scripts/r18_install_cron.sh   # adds backupfresh cron
#
# Safe to re-run. Reports a Gate B activation checklist on success.

set -euo pipefail

LEADPEEK_DIR="${LEADPEEK_DIR:-/opt/leadpeek}"
SCRIPTS_DIR="$LEADPEEK_DIR/scripts"
DEPLOY_DIR="$LEADPEEK_DIR/deploy"
SYSTEMD_DIR="/etc/systemd/system"

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
fail() { log "FAIL: $*"; exit 1; }

# --- 1. preflight ----------------------------------------------------------

[ "$(id -u)" = "0" ] || fail "must run as root"

PG_BIN="/usr/lib/postgresql/16/bin"
[ -x "$PG_BIN/pg_dump" ] || fail "$PG_BIN/pg_dump missing — Postgres 16 client tools required"
[ -x "$PG_BIN/pg_restore" ] || fail "$PG_BIN/pg_restore missing"

[ -f /etc/leadpeek/backup.env ] || fail "/etc/leadpeek/backup.env missing — create it before running"
[ "$(stat -c '%a' /etc/leadpeek/backup.env)" = "600" ] || fail "/etc/leadpeek/backup.env must be mode 600"
[ -f /root/.pgpass ] || fail "/root/.pgpass missing"
[ "$(stat -c '%a' /root/.pgpass)" = "600" ] || fail "/root/.pgpass must be mode 600"

REQUIRED_VARS=(PGHOST PGPORT PGUSER PGDATABASE PGPASSFILE)
# shellcheck disable=SC1091
set -a; . /etc/leadpeek/backup.env; set +a
for v in "${REQUIRED_VARS[@]}"; do
    eval "val=\${$v:-}"
    [ -n "$val" ] || fail "/etc/leadpeek/backup.env: $v not set"
done

[ -d /mnt/volume-hel1-1 ] || fail "/mnt/volume-hel1-1 not mounted"

PHASE2A_SCRIPTS=(leadpeek_backup.sh leadpeek_watchdog_backupfresh.sh r18_alert.sh r18_scrub_journal.sh)
PHASE2B_SCRIPTS=(leadpeek_watchdog_disk.sh leadpeek_watchdog_pgwal.sh leadpeek_watchdog_longtx.sh leadpeek_action_root_disk.sh leadpeek_breaker_tier1.sh leadpeek_breaker_tier2.sh)
PHASE2C_SCRIPTS=(leadpeek_drill_schema.sh leadpeek_drill_partial.sh leadpeek_drill_full.sh leadpeek_check_bloat.sh leadpeek_watchdog_meta.sh)
ALL_SCRIPTS=("${PHASE2A_SCRIPTS[@]}" "${PHASE2B_SCRIPTS[@]}" "${PHASE2C_SCRIPTS[@]}")

for f in "${ALL_SCRIPTS[@]}"; do
    [ -f "$SCRIPTS_DIR/$f" ] || fail "$SCRIPTS_DIR/$f missing — git pull on /opt/leadpeek?"
done

for f in leadpeek-backup.service leadpeek-backup.timer leadpeek-backup-failure.service breaker_pg_hba.conf; do
    [ -f "$DEPLOY_DIR/$f" ] || fail "$DEPLOY_DIR/$f missing — git pull on /opt/leadpeek?"
done

# --- 2. install scripts ---------------------------------------------------

log "marking scripts executable"
for f in "${ALL_SCRIPTS[@]}"; do
    chmod 755 "$SCRIPTS_DIR/$f"
done

# Smoke-test all helpers for parse errors (won't actually run them)
for f in "${ALL_SCRIPTS[@]}"; do
    bash -n "$SCRIPTS_DIR/$f" || fail "$f has bash syntax errors"
done

# Quick scrub self-test: known credential strings must be redacted
SCRUB_TEST=$(printf 'PGPASSWORD=hunter2 oops\npostgres://u:p@host/db\nuser=alice password=foo\nAuthorization: Bearer xyz789\nAPI_KEY: sk-secret-123\n' \
    | bash "$SCRIPTS_DIR/r18_scrub_journal.sh")
case "$SCRUB_TEST" in
    *hunter2*|*"u:p@"*|*"=alice"*|*"=foo"*|*xyz789*|*"sk-secret-123"*)
        fail "r18_scrub_journal.sh self-test failed — credentials leaked through scrub"
        ;;
esac

# --- 3. install systemd units ---------------------------------------------

for f in leadpeek-backup.service leadpeek-backup.timer leadpeek-backup-failure.service; do
    log "installing $SYSTEMD_DIR/$f"
    install -m 644 "$DEPLOY_DIR/$f" "$SYSTEMD_DIR/$f"
done

log "systemctl daemon-reload"
systemctl daemon-reload

# --- 4. report -------------------------------------------------------------

log "=== R18 staging COMPLETE (Phase 2a + 2b) ==="
cat <<'EOM'

--- Files staged ---
Phase 2a (backup automation):
  /opt/leadpeek/scripts/leadpeek_backup.sh                (production backup)
  /opt/leadpeek/scripts/leadpeek_watchdog_backupfresh.sh  (freshness alert)
  /opt/leadpeek/scripts/r18_alert.sh                      (alert helper)
  /opt/leadpeek/scripts/r18_scrub_journal.sh              (credential scrub)
  /etc/systemd/system/leadpeek-backup.{service,timer}     (every 2 days)
  /etc/systemd/system/leadpeek-backup-failure.service     (OnFailure email)

Phase 2b (watchdogs + circuit breakers):
  /opt/leadpeek/scripts/leadpeek_watchdog_disk.sh         (5min, alert at vol>150G/root>55G)
  /opt/leadpeek/scripts/leadpeek_watchdog_pgwal.sh        (1min, alert>6G, action>8G sustained 5min)
  /opt/leadpeek/scripts/leadpeek_watchdog_longtx.sh       (5min, cancel idle-tx>1h, warn>2h)
  /opt/leadpeek/scripts/leadpeek_action_root_disk.sh      (10min, prune+rotate at root>65G)
  /opt/leadpeek/scripts/leadpeek_breaker_tier1.sh         (1min, stop enrichment at vol>175G)
  /opt/leadpeek/scripts/leadpeek_breaker_tier2.sh         (1min, full RO at vol>185G)
  /opt/leadpeek/deploy/breaker_pg_hba.conf                (Tier-2 RO override)

Phase 2c (drills + bloat + meta):
  /opt/leadpeek/scripts/leadpeek_drill_schema.sh          (weekly, full schema-only restore)
  /opt/leadpeek/scripts/leadpeek_drill_partial.sh         (monthly, top-5 tables data restore)
  /opt/leadpeek/scripts/leadpeek_drill_full.sh            (quarterly, full restore best-effort)
  /opt/leadpeek/scripts/leadpeek_check_bloat.sh           (weekly pgstattuple check)
  /opt/leadpeek/scripts/leadpeek_watchdog_meta.sh         (30min, all watchdogs ran recently)

Nothing has been enabled or started. Cron entries are not yet installed.
Gate B activation (below) requires explicit operator approval.

--- Gate B activation (requires operator approval) ---

  # 1. Enable the backup timer (Phase 2a goes live)
  systemctl enable --now leadpeek-backup.timer

  # 2. Install all R18 cron entries (Phase 2a freshness + Phase 2b watchdogs/breakers)
  bash /opt/leadpeek/scripts/r18_install_cron.sh

  # 3. Verify
  systemctl list-timers leadpeek-backup.timer --no-pager
  crontab -l | grep -A30 R18-MANAGED

  # 4. (Optional) Trigger one immediate backup run
  systemctl start leadpeek-backup.service
  journalctl -u leadpeek-backup.service -f

--- Rollback ---

  # Disable Phase 2a timer:
  systemctl disable --now leadpeek-backup.timer
  # Remove all R18 crons (snapshot is automatically saved to /root/crontab-backups/):
  bash -c "crontab -l | sed '/^# R18-MANAGED-BEGIN/,/^# R18-MANAGED-END/d' | crontab -"
  # Reset a tripped breaker manually — see docs/r18-operations.md.

EOM
