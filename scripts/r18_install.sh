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

for f in leadpeek_backup.sh leadpeek_watchdog_backupfresh.sh r18_alert.sh r18_scrub_journal.sh; do
    [ -f "$SCRIPTS_DIR/$f" ] || fail "$SCRIPTS_DIR/$f missing — git pull on /opt/leadpeek?"
done

for f in leadpeek-backup.service leadpeek-backup.timer leadpeek-backup-failure.service; do
    [ -f "$DEPLOY_DIR/$f" ] || fail "$DEPLOY_DIR/$f missing — git pull on /opt/leadpeek?"
done

# --- 2. install scripts ---------------------------------------------------

log "marking scripts executable"
chmod 755 "$SCRIPTS_DIR/leadpeek_backup.sh"
chmod 755 "$SCRIPTS_DIR/leadpeek_watchdog_backupfresh.sh"
chmod 755 "$SCRIPTS_DIR/r18_alert.sh"
chmod 755 "$SCRIPTS_DIR/r18_scrub_journal.sh"

# Smoke-test the helpers for parse errors (won't actually send if backend is down)
bash -n "$SCRIPTS_DIR/r18_alert.sh" || fail "r18_alert.sh has bash syntax errors"
bash -n "$SCRIPTS_DIR/r18_scrub_journal.sh" || fail "r18_scrub_journal.sh has bash syntax errors"
bash -n "$SCRIPTS_DIR/leadpeek_backup.sh" || fail "leadpeek_backup.sh has bash syntax errors"
bash -n "$SCRIPTS_DIR/leadpeek_watchdog_backupfresh.sh" || fail "leadpeek_watchdog_backupfresh.sh has bash syntax errors"

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

log "=== R18 Phase 2a staging COMPLETE ==="
cat <<'EOM'

--- Files staged ---
  /opt/leadpeek/scripts/leadpeek_backup.sh                (production backup)
  /opt/leadpeek/scripts/leadpeek_watchdog_backupfresh.sh  (freshness alert)
  /opt/leadpeek/scripts/r18_alert.sh                      (alert helper)
  /etc/systemd/system/leadpeek-backup.service             (oneshot)
  /etc/systemd/system/leadpeek-backup.timer               (every 2 days, 02:00 UTC)
  /etc/systemd/system/leadpeek-backup-failure.service     (OnFailure email)

Nothing has been enabled or started. The next step is Gate B, which
requires explicit operator approval.

--- Gate B activation (requires operator approval) ---

  # 1. Enable the timer (this is the moment Phase 2a goes live)
  systemctl enable --now leadpeek-backup.timer

  # 2. Verify the timer is scheduled
  systemctl list-timers leadpeek-backup.timer --no-pager

  # 3. (Optional) Trigger one immediate run to confirm it works end-to-end
  systemctl start leadpeek-backup.service
  journalctl -u leadpeek-backup.service -f

  # 4. Add the freshness watchdog cron (separate script — keeps changes
  #    to managed cron block isolated from this systemd staging step)
  bash /opt/leadpeek/scripts/r18_install_cron.sh

--- Rollback ---

  # If the timer goes wrong, disable it without touching anything else:
  systemctl disable --now leadpeek-backup.timer
  # The most recent verified dump is at:
  #   /mnt/volume-hel1-1/backups/CURRENT.dump.zst         (volume primary)
  #   /var/lib/postgresql/backups/PREVIOUS.dump.zst       (root copy)
  # Either is restorable with /usr/lib/postgresql/16/bin/pg_restore.

EOM
