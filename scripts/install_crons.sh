#!/bin/bash
# Install/update all DataSnoop cron jobs on the Hetzner host.
# Idempotent: re-running replaces all cron entries managed here.
#
# Usage: ssh root@hetzner "bash /opt/leadpeek/scripts/install_crons.sh"
#
# Existing jobs preserved:
#   - daily_update.sh at 03:00
#   - kbo_cron.sh at 06:00
#   - nbb_batch_pipeline.py at 01:00
#   - nbb_watchdog.sh every 15 min
#
# New jobs installed:
#   - nbb_nightly_backload.py at 02:00 (4-hour timeout, 5000 calls/run)
#   - invoice_ingest.py at 04:00
#   - open_data_ted.py at 05:00
#   - open_data_staatsblad_events.py at 04:30
#   - open_data_regsol.py at 03:30 (batch 200)
#   - alert_digest.py weekly Mondays 07:00

set -euo pipefail

LOG_DIR="/opt/leadpeek/scripts/_watchdog_state"
mkdir -p "$LOG_DIR"

# Preserve any non-managed entries, then replace the managed block.
CURRENT=$(crontab -l 2>/dev/null || true)

# Strip the old managed block
FILTERED=$(echo "$CURRENT" | awk '
  /^# DATASNOOP-MANAGED-BEGIN$/ { skip=1; next }
  /^# DATASNOOP-MANAGED-END$/ { skip=0; next }
  !skip { print }
')

NEW_BLOCK=$(cat <<'EOF'
# DATASNOOP-MANAGED-BEGIN
# NBB nightly backload (reverse chronological, FY2024 → FY2022 — newer years
# are too sparse this early in 2026; re-enable later when filings exist)
0 2 * * * cd /opt/leadpeek && docker exec -e PYTHONPATH=/app leadpeek-backend-1 timeout 4h python /app/scripts/nbb_nightly_backload.py --max-calls 10000 >> /opt/leadpeek/scripts/_watchdog_state/nightly.log 2>&1
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
# DATASNOOP-MANAGED-END
EOF
)

# Write the merged crontab
echo -e "${FILTERED}\n${NEW_BLOCK}" | crontab -
echo "Installed managed cron block. Current:"
crontab -l
