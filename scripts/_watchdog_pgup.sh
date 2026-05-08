#!/bin/bash
# DataSnoop R18 — Postgres-up watchdog.
# Runs every minute via cron. On 3 consecutive "no response" probes, attempts
# auto-recovery: stop enrichment-worker, reset-failed, restart postgresql@16-main,
# then re-start enrichment-worker once PG is back up.
#
# pg_isready exit codes:
#   0 = accepting connections (UP)
#   1 = rejecting connections (RECOVERING — startup/shutdown). Tracked separately;
#       alerts (no auto-restart) after 30 min sustained, since restart cannot fix
#       corruption-driven hangs.
#   2 = no response (TRUE DOWN). After 3 ticks: alert + auto-recover.
#   * = unexpected; log and skip.
#
# Maintenance flag: /opt/leadpeek/.maintenance — when present, watchdog exits 0
# without probing or acting. Use during planned PG operations.
#
# Cooldown: /opt/leadpeek/scripts/_watchdog_state/pgup.cooldown is touched at the
# START of any action block, gating subsequent ticks during the action's runtime.
set -uo pipefail
STATE=/opt/leadpeek/scripts/_watchdog_state
COOLDOWN=$STATE/pgup.cooldown
COUNTER=$STATE/pgup.consec_fail
RECOVER_COUNTER=$STATE/pgup.consec_recover
RECOVER_ALERT_STAMP=$STATE/pgup.recover_alerted
LOG=$STATE/pgup.log
MAINT=/opt/leadpeek/.maintenance
COMPOSE=/opt/leadpeek/docker-compose.yml
ALERT=/opt/leadpeek/scripts/r18_alert.sh

install -d -m 755 "$STATE"

# Cooldown gate
if [ -f "$COOLDOWN" ] && [ $(( $(date +%s) - $(stat -c %Y "$COOLDOWN") )) -lt 600 ]; then
    echo "$(date -uIs) cooldown active, skipping" >> "$LOG"
    exit 0
fi

# Maintenance flag
if [ -f "$MAINT" ]; then
    echo "$(date -uIs) maintenance flag set, skipping" >> "$LOG"
    exit 0
fi

# Probe — distinguish exit codes
pg_isready -h /var/run/postgresql -U postgres -d leadpeek -t 5 >/dev/null 2>&1
rc=$?
case "$rc" in
    0)
        rm -f "$COUNTER" "$RECOVER_COUNTER" "$RECOVER_ALERT_STAMP"
        echo "$(date -uIs) tick: pg up" >> "$LOG"
        exit 0
        ;;
    1)
        rfails=$(( $(cat "$RECOVER_COUNTER" 2>/dev/null || echo 0) + 1 ))
        echo "$rfails" > "$RECOVER_COUNTER"
        rm -f "$COUNTER"
        echo "$(date -uIs) tick: pg recovering (rc=1), consec_recover=$rfails" >> "$LOG"
        if [ "$rfails" -ge 30 ] && [ ! -f "$RECOVER_ALERT_STAMP" ]; then
            if "$ALERT" "pg-stuck-recovery" "PostgreSQL has been in 'rejecting connections' state (pg_isready rc=1) for 30+ consecutive watchdog ticks (~30 min). NOT auto-restarting — restart will not fix corruption. Operator action required."; then
                touch "$RECOVER_ALERT_STAMP"
            else
                echo "$(date -uIs) WARN: r18_alert.sh failed; will retry next tick" >> "$LOG"
            fi
        fi
        exit 0
        ;;
    2)  ;;  # true down — fall through to action
    *)
        echo "$(date -uIs) tick: pg_isready unexpected rc=$rc, skipping" >> "$LOG"
        exit 0
        ;;
esac

# Failure path (rc=2)
rm -f "$RECOVER_COUNTER" "$RECOVER_ALERT_STAMP"
fails=$(( $(cat "$COUNTER" 2>/dev/null || echo 0) + 1 ))
echo "$fails" > "$COUNTER"
echo "$(date -uIs) tick: pg DOWN (rc=2), consec_fail=$fails" >> "$LOG"

if [ "$fails" -ge 3 ]; then
    # Cooldown stamped FIRST so re-entrant ticks bail before any action
    touch "$COOLDOWN"
    rm -f "$COUNTER"
    echo "$(date -uIs) ACTING: cooldown set, beginning recovery" >> "$LOG"

    "$ALERT" "pg-down" "PostgreSQL has been unreachable (no response) for 3 consecutive watchdog ticks (~3 min). Stopping enrichment-worker, then attempting recovery." || true

    # Stop enrichment-worker first (defends against re-OOM if PG died from memory pressure)
    timeout 30s docker compose -f "$COMPOSE" stop --timeout 0 enrichment-worker >> "$LOG" 2>&1 || true
    sleep 5
    mem_avail=$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)
    swap_free=$(awk '/^SwapFree:/ {print $2}' /proc/meminfo)
    echo "$(date -uIs) post-stop headroom: avail=${mem_avail}kB swap=${swap_free}kB sum=$((mem_avail + swap_free))kB" >> "$LOG"

    timeout 30s  systemctl reset-failed postgresql@16-main >> "$LOG" 2>&1 || true
    timeout 360s systemctl restart      postgresql@16-main >> "$LOG" 2>&1 || true

    # Re-probe with bounded wait (max 30s), then start enrichment-worker
    for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
        sleep 2
        if pg_isready -h /var/run/postgresql -U postgres -d leadpeek -t 3 >/dev/null 2>&1; then
            echo "$(date -uIs) pg up after $((i*2))s" >> "$LOG"
            break
        fi
    done
    timeout 30s docker compose -f "$COMPOSE" start enrichment-worker >> "$LOG" 2>&1 || true

    echo "$(date -uIs) ACTED: recovery sequence complete" >> "$LOG"
fi
