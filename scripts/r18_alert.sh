#!/bin/bash
# R18-specific alert helper. Mirrors scripts/_watchdog_send_alert.sh but with
# R18 subject prefixes; both share the same SMTP-via-backend-container path so
# we don't fork the email-sending logic.
#
# Usage: r18_alert.sh <kind> <body>
#
# SMTP creds come from the backend container's env (loaded from .env.production).
# Body is piped via stdin; subject + meta via env vars to survive quoting.
#
# Reliability: any failure (container down, docker exec error, Python error,
# SMTP error, missing creds) spools the alert to /var/spool/leadpeek-alerts/
# (persistent across reboot — distinct from /run tmpfs which evaporates).

set -uo pipefail

KIND="${1:-unknown}"
BODY="${2:-(no detail)}"

case "$KIND" in
    backup-ok)              SUBJECT="[DataSnoop R18] backup OK" ;;
    backup-fail)            SUBJECT="[DataSnoop R18] BACKUP FAILED — manual intervention needed" ;;
    backup-degraded-no-root) SUBJECT="[DataSnoop R18] backup degraded — off-volume copy skipped" ;;
    backup-stale)           SUBJECT="[DataSnoop R18] backup STALE — newest dump is too old" ;;
    backup-sha-mismatch)    SUBJECT="[DataSnoop R18] backup integrity FAIL — SHA256 mismatch" ;;
    pgwal-warn)             SUBJECT="[DataSnoop R18] pg_wal size warning" ;;
    pgwal-action)           SUBJECT="[DataSnoop R18] pg_wal pressure — query cancelled" ;;
    disk-warn)              SUBJECT="[DataSnoop R18] disk usage warning" ;;
    disk-tier1)             SUBJECT="[DataSnoop R18] TIER-1 BREAKER — enrichment worker stopped" ;;
    disk-tier2)             SUBJECT="[DataSnoop R18] TIER-2 BREAKER — full read-only mode" ;;
    root-disk-action)       SUBJECT="[DataSnoop R18] root disk action — pruned + rotated" ;;
    longtx-cancel)          SUBJECT="[DataSnoop R18] long transaction cancelled" ;;
    longtx-warn)            SUBJECT="[DataSnoop R18] long transaction running > 2h" ;;
    drill-pass)             SUBJECT="[DataSnoop R18] restore drill OK" ;;
    drill-fail)             SUBJECT="[DataSnoop R18] RESTORE DRILL FAILED" ;;
    drill-skipped)          SUBJECT="[DataSnoop R18] restore drill skipped (insufficient space)" ;;
    bloat-warn)             SUBJECT="[DataSnoop R18] table bloat over threshold" ;;
    meta-watchdog-stale)    SUBJECT="[DataSnoop R18] watchdog has not run recently" ;;
    *)                      SUBJECT="[DataSnoop R18] event: $KIND" ;;
esac

HOSTNAME_STR="$(uname -n)"
TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# Persistent spool — /var survives reboot, /run/tmpfs does not.
SPOOL_DIR="/var/spool/leadpeek-alerts"
install -d -m 700 "$SPOOL_DIR" 2>/dev/null || mkdir -p "$SPOOL_DIR"
chmod 700 "$SPOOL_DIR" 2>/dev/null || true

spool_alert() {
    local reason="$1"
    local file="$SPOOL_DIR/$(date -u +%Y%m%dT%H%M%S)-$KIND.txt"
    {
        echo "Subject: $SUBJECT"
        echo "Kind:    $KIND"
        echo "Host:    $HOSTNAME_STR"
        echo "Time:    $TS"
        echo "Reason:  $reason"
        echo "---"
        echo "$BODY"
    } > "$file" 2>/dev/null || return 1
    echo "spooled alert to $file ($reason)" >&2
}

if ! docker ps --format '{{.Names}}' | grep -qx leadpeek-backend-1; then
    spool_alert "backend container not running"
    exit 0
fi

# Send via the backend container's SMTP. On ANY failure (docker exec error,
# Python error, missing creds, network error, Stalwart down), spool to disk
# rather than silently dropping the alert.
TMP_OUT=$(mktemp /tmp/r18_alert_out.XXXXXX)
trap 'rm -f "$TMP_OUT"' EXIT

printf '%s' "$BODY" | docker exec -i \
    -e WATCHDOG_SUBJECT="$SUBJECT" \
    -e WATCHDOG_KIND="$KIND" \
    -e WATCHDOG_HOST="$HOSTNAME_STR" \
    -e WATCHDOG_TS="$TS" \
    leadpeek-backend-1 python3 - >"$TMP_OUT" 2>&1 <<'PYEOF'
import os, smtplib, ssl, sys
from email.mime.text import MIMEText

host    = os.getenv("SMTP_HOST")
port    = int(os.getenv("SMTP_PORT", "587"))
user    = os.getenv("SMTP_USER")
pwd     = os.getenv("SMTP_PASS")
sender  = os.getenv("SMTP_FROM", "claude@datasnoop.be")
to      = os.getenv("SMTP_ALERT_TO")
subject = os.getenv("WATCHDOG_SUBJECT", "[DataSnoop R18] event")
kind    = os.getenv("WATCHDOG_KIND", "unknown")
hostn   = os.getenv("WATCHDOG_HOST", "?")
ts      = os.getenv("WATCHDOG_TS", "")

if not (host and user and pwd and to):
    print("Missing SMTP config - cannot send.", file=sys.stderr)
    sys.exit(1)

body_in = sys.stdin.read()
text_body = (
    f"{subject}\n"
    f"\n"
    f"R18 event:  {kind}\n"
    f"Host:       {hostn}\n"
    f"Time:       {ts}\n"
    f"\n"
    f"--- Detail ---\n"
    f"{body_in}\n"
)

msg = MIMEText(text_body, "plain", "utf-8")
msg["Subject"] = subject
msg["From"]    = f"DataSnoop R18 <{sender}>"
msg["To"]      = to

# Stalwart runs on the host (reached via 'host.docker.internal' from the
# backend container's network). Its TLS cert is for the public datasnoop.be
# name, not the docker-DNS alias, so hostname verification fails. We're on
# loopback either way (docker bridge), so disabling verification is safe.
# Matches scripts/_watchdog_send_alert.sh which uses the same pattern.
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
with smtplib.SMTP(host, port, timeout=20) as s:
    s.ehlo("datasnoop-backend")
    s.starttls(context=ctx)
    s.ehlo("datasnoop-backend")
    s.login(user, pwd)
    s.sendmail(sender, [to], msg.as_string())
print(f"r18 alert sent to {to} ({kind})")
PYEOF
EXEC_RC=$?

if [ "$EXEC_RC" = "0" ]; then
    cat "$TMP_OUT" >&2
    exit 0
fi

spool_alert "smtp/python error rc=$EXEC_RC: $(tail -3 "$TMP_OUT" 2>/dev/null | tr '\n' ' ')"
exit 0
