#!/bin/bash
# Helper: send a watchdog alert email.
#
# Usage: _watchdog_send_alert.sh <kind> <body>
#   kind in {rotating, rotated-ok, rotate-failed, still-red-after-rotate,
#            probe-transient-no-rotate}
#
# Body and subject are passed via -e env vars to docker exec so quoting,
# newlines, and special characters survive intact. SMTP credentials are
# already in the backend container's env (loaded from .env.production).

set -euo pipefail

KIND="${1:-unknown}"
BODY="${2:-(no detail)}"

case "$KIND" in
    rotating)                  SUBJECT="[DataSnoop] NBB keys failed - auto-rotation in progress" ;;
    rotated-ok)                SUBJECT="[DataSnoop] NBB keys auto-rotated successfully" ;;
    rotate-failed)             SUBJECT="[DataSnoop] NBB AUTO-ROTATE FAILED - manual intervention needed" ;;
    still-red-after-rotate)    SUBJECT="[DataSnoop] NBB still red after recent auto-rotate - investigate" ;;
    probe-transient-no-rotate) SUBJECT="[DataSnoop] NBB API briefly unreachable (informational, no action needed)" ;;
    *)                         SUBJECT="[DataSnoop] NBB watchdog: $KIND" ;;
esac

HOSTNAME_STR="$(uname -n)"
TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# Pipe body via stdin and pass subject + meta via env. The Python script
# reads the body from sys.stdin so it survives any quoting.
printf '%s' "$BODY" | docker exec -i \
    -e WATCHDOG_SUBJECT="$SUBJECT" \
    -e WATCHDOG_KIND="$KIND" \
    -e WATCHDOG_HOST="$HOSTNAME_STR" \
    -e WATCHDOG_TS="$TS" \
    leadpeek-backend-1 python - <<'PYEOF'
import os, smtplib, ssl, sys
from email.mime.text import MIMEText

host    = os.getenv("SMTP_HOST")
port    = int(os.getenv("SMTP_PORT", "587"))
user    = os.getenv("SMTP_USER")
pwd     = os.getenv("SMTP_PASS")
sender  = os.getenv("SMTP_FROM", "claude@datasnoop.be")
to      = os.getenv("SMTP_ALERT_TO")
subject = os.getenv("WATCHDOG_SUBJECT", "[DataSnoop] NBB watchdog")
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
    f"Watchdog state: {kind}\n"
    f"Host: {hostn}\n"
    f"Time: {ts}\n"
    f"\n"
    f"--- Detail ---\n"
    f"{body_in}\n"
)

msg = MIMEText(text_body, "plain", "utf-8")
msg["Subject"] = subject
msg["From"]    = f"DataSnoop Watchdog <{sender}>"
msg["To"]      = to

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
with smtplib.SMTP(host, port, timeout=20) as s:
    s.ehlo("datasnoop-backend")
    s.starttls(context=ctx)
    s.ehlo("datasnoop-backend")
    s.login(user, pwd)
    s.sendmail(sender, [to], msg.as_string())
print(f"alert sent to {to} ({kind})")
PYEOF
