#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

CONFIRM_TOKEN="DROP_STAGE_D_BACKUPS_AFTER_DAY7"
if [[ "${STAGE_D_CLEANUP_CONFIRM:-}" != "$CONFIRM_TOKEN" ]]; then
  echo "Refusing cleanup: set STAGE_D_CLEANUP_CONFIRM=$CONFIRM_TOKEN after the day+7 retention window." >&2
  exit 1
fi

if [[ -z "${STAGE_D_APPLY_DATE:-}" ]]; then
  echo "Refusing cleanup: set STAGE_D_APPLY_DATE=YYYY-MM-DD from the actual Stage D apply date." >&2
  exit 1
fi

cleanup_not_before="$(date -u -d "${STAGE_D_APPLY_DATE} +7 days" +%F)"
today_utc="$(date -u +%F)"
if [[ "$today_utc" < "$cleanup_not_before" ]]; then
  echo "Refusing cleanup: today is $today_utc UTC; run on or after $cleanup_not_before UTC." >&2
  exit 1
fi

exec ops/_psql_prod_file.sh -v ON_ERROR_STOP=1 -v stage_d_cleanup_confirmed=1 -f ops/stage_d_cleanup_day7.sql
