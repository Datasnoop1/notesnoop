#!/bin/bash
# Wraps nbb_key_rotate.py: runs the playwright rotator inside an
# off-the-shelf playwright container, then force-recreates the backend
# (prod + staging) so the new env values take effect, then verifies via
# the existing health check.
#
# Designed to be run on the Hetzner host (not inside any of our app
# containers). Idempotent: re-running picks up wherever it left off.
#
# Usage:
#   ./scripts/nbb_rotate_and_restart.sh           # full rotation + restart + verify
#   ./scripts/nbb_rotate_and_restart.sh --dry-run # log in, read current keys, exit
#
# Exit codes:
#   0 success
#   1 rotation failed (env files unchanged)
#   2 rotation succeeded but containers failed to recreate
#   3 containers recreated but health check still failing

set -euo pipefail

LEADPEEK_DIR="${LEADPEEK_DIR:-/opt/leadpeek}"
DRY_RUN_FLAG=""
ROTATE_FLAG="--rotate"
if [ "${1:-}" = "--dry-run" ]; then
    DRY_RUN_FLAG="--dry-run"
    ROTATE_FLAG=""
fi

PLAYWRIGHT_IMAGE="mcr.microsoft.com/playwright/python:v1.58.0-jammy"
mkdir -p "$LEADPEEK_DIR/scripts/_rotate_debug"

echo "==> Pulling playwright container (one-time, cached afterwards)..."
docker pull -q "$PLAYWRIGHT_IMAGE"

echo "==> Running rotator ($([ -n "$DRY_RUN_FLAG" ] && echo 'DRY-RUN' || echo 'LIVE'))..."
# We mount /opt/leadpeek read-write because the script writes new env values.
# The script reads env vars from /data/.env.production via env-file flag.
docker run --rm \
    --network host \
    -v "$LEADPEEK_DIR:/data:rw" \
    --env-file "$LEADPEEK_DIR/.env.production" \
    -e NBB_ROTATE_DEBUG_DIR=/data/scripts/_rotate_debug \
    -e NBB_ENV_FILES=/data/.env.production,/data/.env \
    "$PLAYWRIGHT_IMAGE" \
    python /data/scripts/nbb_key_rotate.py $DRY_RUN_FLAG $ROTATE_FLAG
ROT_EXIT=$?

if [ $ROT_EXIT -ne 0 ]; then
    echo "!! Rotation failed with exit code $ROT_EXIT"
    exit 1
fi

if [ -n "$DRY_RUN_FLAG" ]; then
    echo "==> Dry-run complete. No containers recreated."
    exit 0
fi

echo "==> Force-recreating prod backend + frontend..."
( cd "$LEADPEEK_DIR" && docker compose up -d --force-recreate backend frontend ) || {
    echo "!! Prod recreate failed"
    exit 2
}

if [ -f "$LEADPEEK_DIR/docker-compose.staging.yml" ]; then
    echo "==> Force-recreating staging backend + frontend..."
    ( cd "$LEADPEEK_DIR" && docker compose -f docker-compose.staging.yml -p leadpeek-staging up -d --force-recreate backend-staging frontend-staging ) || {
        echo "!! Staging recreate failed (prod still healthy)"
    }
fi

echo "==> Waiting 10s for backend to settle, then probing health check..."
sleep 10

if docker exec leadpeek-backend-1 python /app/scripts/alert_digest.py --health-check; then
    echo "==> All probes green. Rotation successful."
    exit 0
else
    echo "!! Health check still failing after rotation. Investigate immediately."
    exit 3
fi
