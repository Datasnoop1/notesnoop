#!/bin/bash
# Add R18 Phase 2a watchdog cron entries to the managed crontab block.
# Idempotent: re-running replaces the R18 sub-block.
#
# Run only after r18_install.sh has succeeded and the operator has approved
# Gate B activation.

set -euo pipefail

CURRENT=$(crontab -l 2>/dev/null || true)

# Snapshot before anything destructive — recovery if this script ever
# corrupts the crontab.
BACKUP_DIR=/root/crontab-backups
install -d -m 700 "$BACKUP_DIR"
BACKUP_FILE="$BACKUP_DIR/crontab.$(date -u +%Y%m%dT%H%M%SZ).bak"
printf '%s\n' "$CURRENT" > "$BACKUP_FILE"
chmod 600 "$BACKUP_FILE"
echo "snapshot: $BACKUP_FILE"

# Reject if the existing crontab contains more than one BEGIN or END marker
# (means a previous run left it desynced; refuse to compound the damage).
BEGIN_COUNT=$(printf '%s\n' "$CURRENT" | grep -c '^# R18-MANAGED-BEGIN$' || true)
END_COUNT=$(printf '%s\n' "$CURRENT"   | grep -c '^# R18-MANAGED-END$' || true)
if [ "$BEGIN_COUNT" -gt 1 ] || [ "$END_COUNT" -gt 1 ] || [ "$BEGIN_COUNT" != "$END_COUNT" ]; then
    echo "REFUSING: crontab has $BEGIN_COUNT BEGIN / $END_COUNT END markers — manually clean before re-running"
    exit 2
fi

# Strip any pre-existing R18 sub-block so this script is idempotent.
FILTERED=$(printf '%s\n' "$CURRENT" | awk '
  /^# R18-MANAGED-BEGIN$/ { skip=1; next }
  /^# R18-MANAGED-END$/ { skip=0; next }
  !skip { print }
')

# Sanity: if CURRENT was non-empty but FILTERED is empty, awk failed
# (or the entire crontab was inside the managed block somehow). Refuse to
# write — would clobber the existing 10+ managed cron jobs (Supabase
# keepalive, nightly health report, NBB watchdog, etc).
if [ -n "$CURRENT" ] && [ -z "$FILTERED" ]; then
    echo "REFUSING: filter produced empty output for non-empty crontab. Snapshot saved at $BACKUP_FILE."
    exit 2
fi

R18_BLOCK=$(cat <<'EOF'
# R18-MANAGED-BEGIN
# Backup-freshness watchdog — alerts if newest dump is older than the
# 72h volume / 120h root budgets. Runs hourly; alert helper de-dupes via
# 12h cooldown so a sustained stale window emails twice a day at most.
17 * * * * bash /opt/leadpeek/scripts/leadpeek_watchdog_backupfresh.sh >> /opt/leadpeek/scripts/_watchdog_state/backupfresh_cron.log 2>&1
# R18-MANAGED-END
EOF
)

NEW=$(printf '%s\n%s\n' "$FILTERED" "$R18_BLOCK")
printf '%s\n' "$NEW" | crontab -

echo "R18 cron block installed. Current crontab tail:"
crontab -l | tail -10
