#!/bin/bash
# DataSnoop R18 — system memory headroom watchdog.
# Runs every minute via cron. Tracks MemAvailable + SwapFree as "headroom".
# WARN at <2 GB headroom (suppressed 60 min between alerts).
# ACTION at <1 GB headroom for 3 consecutive ticks: stop enrichment-worker.
# Recovery is manual — operator restarts the worker after investigating.
#
# Why both thresholds: WARN gives the operator early signal of slow drift;
# ACTION sheds the biggest memory consumer (Playwright Chromium fleet under
# enrichment-worker) before the kernel OOM killer picks an arbitrary target.
set -uo pipefail
STATE=/opt/leadpeek/scripts/_watchdog_state
COUNTER=$STATE/mem.consec_action
WARN_STAMP=$STATE/mem.warn_last
LOG=$STATE/mem.log
COMPOSE=/opt/leadpeek/docker-compose.yml
ALERT=/opt/leadpeek/scripts/r18_alert.sh

install -d -m 755 "$STATE"

mem_avail=$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)
swap_free=$(awk '/^SwapFree:/ {print $2}' /proc/meminfo)
headroom=$(( mem_avail + swap_free ))

WARN_KB=2097152   # 2.0 GB
ACT_KB=1048576    # 1.0 GB

echo "$(date -uIs) tick: mem_avail=${mem_avail}kB swap_free=${swap_free}kB headroom=${headroom}kB" >> "$LOG"

# WARN path (60-min suppression)
if [ "$headroom" -lt "$WARN_KB" ]; then
    last=$( [ -f "$WARN_STAMP" ] && cat "$WARN_STAMP" || echo 0 )
    now=$(date +%s)
    if [ $(( now - last )) -ge 3600 ]; then
        "$ALERT" "mem-warn" "Memory headroom = $((headroom/1024)) MB (warn threshold 2 GB). MemAvailable=$((mem_avail/1024))MB SwapFree=$((swap_free/1024))MB." || true
        echo "$now" > "$WARN_STAMP"
    fi
fi

# ACTION path (3 consecutive ticks below 1 GB)
if [ "$headroom" -lt "$ACT_KB" ]; then
    fails=$(( $(cat "$COUNTER" 2>/dev/null || echo 0) + 1 ))
    echo "$fails" > "$COUNTER"
    if [ "$fails" -ge 3 ]; then
        "$ALERT" "mem-pressure" "Memory headroom under 1 GB for 3 consecutive ticks. Stopping enrichment-worker. Operator must investigate before restarting." || true
        # docker compose stop --timeout 0 sends SIGKILL AND marks the container stopped,
        # so 'restart: always' policies do NOT resurrect them until manual start.
        timeout 30s docker compose -f "$COMPOSE" stop --timeout 0 enrichment-worker >> "$LOG" 2>&1 || true
        rm -f "$COUNTER"
        echo "$(date -uIs) ACTED: stopped enrichment-worker" >> "$LOG"
    fi
else
    rm -f "$COUNTER"
fi
