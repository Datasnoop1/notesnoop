#!/bin/bash
# NBB backload daemon loop. Replaces the cron-triggered docker exec pattern
# that was killed by every backend rebuild — see docs/nbb-loader-operations.md.
#
# Each iteration calls nbb_nightly_backload.py for ~MAX_CALLS API calls (the
# script self-paces at 1.25s per call) and then sleeps a short interval before
# starting again. A short iteration (<5 min) implies 401/429/empty-queue,
# so we back off longer to avoid spamming.
#
# Materialised tables are rebuilt by the daily 01:00 batch, so the daemon
# always passes --skip-rebuild.
#
# Tunables (env vars, all optional):
#   BACKLOAD_MAX_CALLS      per-iteration call budget        (default 3500)
#   BACKLOAD_START_YEAR     reverse-chrono start fiscal year (default 2025)
#   BACKLOAD_END_YEAR       reverse-chrono end fiscal year   (default 2022)
#   BACKLOAD_PER_YEAR_CAP   per-fiscal-year cap per run      (default 3500)
#   BACKLOAD_SLEEP_S        sleep between normal iterations  (default 30)
#   BACKLOAD_BACKOFF_S      sleep after a short iteration    (default 600)

set -uo pipefail

MAX_CALLS="${BACKLOAD_MAX_CALLS:-3500}"
START_YEAR="${BACKLOAD_START_YEAR:-2025}"
END_YEAR="${BACKLOAD_END_YEAR:-2022}"
PER_YEAR_CAP="${BACKLOAD_PER_YEAR_CAP:-3500}"
SLEEP_S="${BACKLOAD_SLEEP_S:-30}"
BACKOFF_S="${BACKLOAD_BACKOFF_S:-600}"

ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }

# Forward SIGTERM/SIGINT to the python child and wait for it to reap before
# exiting. Without the wait, docker would emit a stop_grace_period warning
# and SIGKILL the child — fine for an idempotent loader, but noisy. Compose
# sets stop_grace_period: 30s so the child has plenty of room to finish its
# current 1.25s API call + DB commit.
child_pid=
trap '[ -n "$child_pid" ] && { kill -TERM "$child_pid" 2>/dev/null; wait "$child_pid" 2>/dev/null; }; exit 0' SIGTERM SIGINT

echo "$(ts) nbb-backload-loop starting (max_calls=$MAX_CALLS start=$START_YEAR end=$END_YEAR per_year=$PER_YEAR_CAP sleep=${SLEEP_S}s backoff=${BACKOFF_S}s)"

while true; do
    start=$(date +%s)
    python /app/scripts/nbb_nightly_backload.py \
        --max-calls "$MAX_CALLS" \
        --start-year "$START_YEAR" \
        --end-year "$END_YEAR" \
        --per-year-cap "$PER_YEAR_CAP" \
        --skip-rebuild &
    child_pid=$!
    wait "$child_pid"
    rc=$?
    child_pid=
    elapsed=$(($(date +%s) - start))

    if [ "$elapsed" -lt 300 ]; then
        echo "$(ts) iteration ended after ${elapsed}s rc=$rc — backing off ${BACKOFF_S}s"
        sleep "$BACKOFF_S" &
    else
        echo "$(ts) iteration finished in ${elapsed}s rc=$rc — sleeping ${SLEEP_S}s"
        sleep "$SLEEP_S" &
    fi
    wait $!
done
