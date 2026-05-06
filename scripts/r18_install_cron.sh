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
# Phase 2a — Backup-freshness watchdog (hourly, 12h alert cooldown)
17 * * * * bash /opt/leadpeek/scripts/leadpeek_watchdog_backupfresh.sh >> /opt/leadpeek/scripts/_watchdog_state/backupfresh_cron.log 2>&1
# Phase 2b — Disk-space watchdog (5min, alert at vol>150G or root>55G; 60min repeat cooldown)
*/5 * * * * bash /opt/leadpeek/scripts/leadpeek_watchdog_disk.sh >> /opt/leadpeek/scripts/_watchdog_state/disk_cron.log 2>&1
# Phase 2b — pg_wal size watchdog (1min, alert>6G, sustain-5min cancel>8G; backup_user exempt)
* * * * * bash /opt/leadpeek/scripts/leadpeek_watchdog_pgwal.sh >> /opt/leadpeek/scripts/_watchdog_state/pgwal_cron.log 2>&1
# Phase 2b — Long-transaction watchdog (5min, cancel idle-in-tx>1h, warn>2h; backup_user exempt)
*/5 * * * * bash /opt/leadpeek/scripts/leadpeek_watchdog_longtx.sh >> /opt/leadpeek/scripts/_watchdog_state/longtx_cron.log 2>&1
# Phase 2b — Root disk hygiene (10min, docker prune + logrotate at root>65G with image-protect)
*/10 * * * * bash /opt/leadpeek/scripts/leadpeek_action_root_disk.sh >> /opt/leadpeek/scripts/_watchdog_state/root_disk_action_cron.log 2>&1
# Phase 2b — Tier-1 disk breaker (1min, stop enrichment-worker at vol>175G sustained 2min)
* * * * * bash /opt/leadpeek/scripts/leadpeek_breaker_tier1.sh >> /opt/leadpeek/scripts/_watchdog_state/breaker_tier1_cron.log 2>&1
# Phase 2b — Tier-2 emergency breaker (1min, full RO at vol>185G sustained 2min — manual recovery)
* * * * * bash /opt/leadpeek/scripts/leadpeek_breaker_tier2.sh >> /opt/leadpeek/scripts/_watchdog_state/breaker_tier2_cron.log 2>&1
# Phase 2c — Weekly schema-only restore drill (Sun 03:00 UTC)
0 3 * * SUN bash /opt/leadpeek/scripts/leadpeek_drill_schema.sh >> /opt/leadpeek/scripts/_watchdog_state/drill_schema_cron.log 2>&1
# Phase 2c — Monthly partial restore drill (every Sun; script gates on 1st-of-month)
0 4 * * SUN bash /opt/leadpeek/scripts/leadpeek_drill_partial.sh >> /opt/leadpeek/scripts/_watchdog_state/drill_partial_cron.log 2>&1
# Phase 2c — Quarterly full restore drill (1st Sun of Jan/Apr/Jul/Oct via in-script gate)
0 2 * 1,4,7,10 SUN bash /opt/leadpeek/scripts/leadpeek_drill_full.sh >> /opt/leadpeek/scripts/_watchdog_state/drill_full_cron.log 2>&1
# Phase 2c — Weekly table-bloat check (Sun 05:00 UTC)
0 5 * * SUN bash /opt/leadpeek/scripts/leadpeek_check_bloat.sh >> /opt/leadpeek/scripts/_watchdog_state/bloat_cron.log 2>&1
# Phase 2c — Meta-watchdog (30min, verify all watchdogs ran recently)
*/30 * * * * bash /opt/leadpeek/scripts/leadpeek_watchdog_meta.sh >> /opt/leadpeek/scripts/_watchdog_state/meta_cron.log 2>&1
# R18-MANAGED-END
EOF
)

NEW=$(printf '%s\n%s\n' "$FILTERED" "$R18_BLOCK")
printf '%s\n' "$NEW" | crontab -

echo "R18 cron block installed. Current crontab tail:"
crontab -l | tail -10
