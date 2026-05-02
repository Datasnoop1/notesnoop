#!/bin/bash
# Install/update all DataSnoop cron jobs on the Hetzner host.
# Idempotent: re-running replaces all cron entries managed here.
#
# Usage: ssh root@hetzner "bash /opt/leadpeek/scripts/install_crons.sh"
#
# Existing jobs preserved:
#   - kbo_cron.sh at 06:00
#   - nbb_batch_pipeline.py at 01:00
#   - nbb_watchdog.sh every 15 min
#
# New jobs installed:
#   - daily_update.sh at 03:00 (tracked wrapper; replaces legacy host-only entry)
#   - invoice_ingest.py at 04:00
#   - open_data_ted.py at 05:00
#   - open_data_staatsblad_events.py at 04:30
#   - open_data_regsol.py at 03:30 (batch 200)
#   - alert_digest.py weekly Mondays 07:00
#
# NOTE: the NBB historical backload now runs as the `nbb-backload-worker`
# compose service (continuously), not as a cron entry. See
# docs/nbb-loader-operations.md.

set -euo pipefail

LOG_DIR="/opt/leadpeek/scripts/_watchdog_state"
mkdir -p "$LOG_DIR"

# Preserve any non-managed entries, then replace the managed block.
CURRENT=$(crontab -l 2>/dev/null || true)

# Strip the old managed block + any pre-existing ad-hoc entries that this
# script now manages (added before they were folded into the managed block).
FILTERED=$(echo "$CURRENT" | awk '
  /^# DATASNOOP-MANAGED-BEGIN$/ { skip=1; next }
  /^# DATASNOOP-MANAGED-END$/ { skip=0; next }
  /\/opt\/leadpeek\/scripts\/daily_update\.sh/ { next }
  /backfill_affiliation\.py/ { next }
  # Strip pre-2026-04-27 backload cron entries — replaced by the long-running
  # `nbb-backload-worker` compose service. Keeping the filter idempotent so
  # operators can re-run install_crons.sh on a host with the legacy crons.
  /nbb_backload_cron\.sh/ { next }
  !skip { print }
')

NEW_BLOCK=$(cat <<'EOF'
# DATASNOOP-MANAGED-BEGIN
# Daily NBB + Staatsblad loaders via the backend container. Replaces the old
# host-only daily_update.sh that hardcoded DATABASE_URL / NBB keys and could
# drift out of sync with auto-rotation.
0 3 * * * bash /opt/leadpeek/scripts/daily_update.sh >> /var/log/datapeak_daily.log 2>&1
# NBB historical backload runs continuously as the `nbb-backload-worker`
# compose service (see docker-compose.yml + docs/nbb-loader-operations.md).
# The two pre-2026-04-27 cron entries that fired nbb_backload_cron.sh were
# removed because docker-exec'd runs were SIGKILLed by every backend rebuild.
# Affiliation backfill — re-fetches NBB filings with legal-person admins and
# extracts the natural-person Representatives into the affiliation table.
# 5000 filings/run × ~1.1s per NBB call = ~92 min, well within the 2h gap
# between the 02:00 nightly NBB backload and the 06:00 daytime drip-feed.
# At 5000/day, the ~109k historical backlog clears in ~22 days. Idempotent
# via affiliation_backfill_log so re-runs never repeat work.
0 4 * * * cd /opt/leadpeek && docker exec -e PYTHONPATH=/app leadpeek-backend-1 python /app/scripts/backfill_affiliation.py --max-filings 5000 >> /opt/leadpeek/scripts/_watchdog_state/affiliation_backfill_cron.log 2>&1
# Regsol insolvency scraper (throttled candidates)
30 3 * * * cd /opt/leadpeek && docker exec -e PYTHONPATH=/app leadpeek-backend-1 python /app/scripts/open_data_regsol.py --batch 200 >> /opt/leadpeek/scripts/_watchdog_state/regsol.log 2>&1
# Invoice ingest from invoice@datasnoop.be
0 4 * * * cd /opt/leadpeek && docker exec -e PYTHONPATH=/app leadpeek-backend-1 python /app/scripts/invoice_ingest.py >> /opt/leadpeek/scripts/_watchdog_state/invoices.log 2>&1
# Staatsblad batch-API catch-up (Stage 3 — extracts structured events from new filings)
# Runs every 2 days via Anthropic batch API (50% discount). 24h batch
# turnaround fits comfortably in the 48h cadence. Data lag: up to 72h.
# Supersedes the old regex-classifier (open_data_staatsblad_events.py) and
# the daily regular-API variant (staatsblad_incremental.py).
0 4 */2 * * cd /opt/leadpeek && docker exec -e PYTHONPATH=/app leadpeek-backend-1 python /app/scripts/staatsblad_batch_every_2d.py >> /opt/leadpeek/scripts/_watchdog_state/staatsblad_events.log 2>&1
# Staatsblad event embeddings — generate pgvector embeddings for newly-extracted events.
# Runs daily (cheap: $0.02/1M tokens, ~$2 total for the whole corpus).
45 5 * * * cd /opt/leadpeek && docker exec -e PYTHONPATH=/app leadpeek-backend-1 python /app/scripts/staatsblad_embed.py --batch 200 >> /opt/leadpeek/scripts/_watchdog_state/staatsblad_events.log 2>&1
# TED procurement (last 7 days)
0 5 * * * cd /opt/leadpeek && docker exec -e PYTHONPATH=/app leadpeek-backend-1 python /app/scripts/open_data_ted.py --days 7 >> /opt/leadpeek/scripts/_watchdog_state/ted.log 2>&1
# Valuation AI commentary — pre-generate for favourited / recently-viewed
30 5 * * * cd /opt/leadpeek && docker exec -e PYTHONPATH=/app leadpeek-backend-1 python /app/scripts/generate_valuation_commentary.py --max-calls 50 >> /opt/leadpeek/scripts/_watchdog_state/valuation_commentary.log 2>&1
# Weekly favourites digest
0 7 * * MON cd /opt/leadpeek && docker exec -e PYTHONPATH=/app leadpeek-backend-1 python /app/scripts/alert_digest.py --send >> /opt/leadpeek/scripts/_watchdog_state/digest.log 2>&1
# Nightly automated-process health report — emails t.braet@gmail.com at 06:00 UTC
# with a per-job GREEN/RED status + Claude-ready prompts for any red items.
0 6 * * * cd /opt/leadpeek && docker exec -e PYTHONPATH=/app leadpeek-backend-1 python /app/scripts/nightly_health_report.py --send >> /opt/leadpeek/scripts/_watchdog_state/health_report.log 2>&1
# Search V2 popularity refresh — click-count ranking signal from activity_log.
# Runs at 03:15 UTC (off-peak, after daily KBO updates finish).
15 3 * * * cd /opt/leadpeek && docker exec -e PYTHONPATH=/app leadpeek-backend-1 python /app/scripts/refresh_popularity.py --lookback-days 28 >> /opt/leadpeek/scripts/_watchdog_state/refresh_popularity.log 2>&1
# Monthly restore drill - validates the latest physical backup payload and
# restores a schema-only dump into a scratch DB. Runs first Sunday at 02:20 UTC,
# after the 02:00 staging snapshot window.
20 2 1-7 * SUN bash /opt/leadpeek/scripts/monthly_restore_drill.sh --run >> /opt/leadpeek/scripts/_watchdog_state/restore_drill.log 2>&1
# Supabase keepalive — daily ping to prevent free-tier auto-pause.
# Supabase pauses inactive free-tier projects after 7 days. DataSnoop only
# uses Supabase for auth (DB is on Hetzner), so live users do not generate
# Supabase API traffic. A pause breaks login for everyone.
30 2 * * * /opt/leadpeek/scripts/supabase_keepalive.sh
# DATASNOOP-MANAGED-END
EOF
)

# Write the merged crontab
echo -e "${FILTERED}\n${NEW_BLOCK}" | crontab -
echo "Installed managed cron block. Current:"
crontab -l
