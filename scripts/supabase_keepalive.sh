#!/bin/bash
# Daily keepalive ping to the Supabase free-tier project.
#
# Why: Supabase auto-pauses free-tier projects after 7 days of inactivity.
# DataSnoop only uses Supabase for auth (DB lives on Hetzner), so most logged-in
# users never trigger a Supabase API call — the project can look "inactive"
# even with active users. A pause breaks login for everyone, with a 90-day
# unpause window before data is download-only.
#
# What: a single GET to PostgREST with the anon key. Counts as project activity
# regardless of whether any rows are returned.

set -uo pipefail

ENV_FILE=/opt/leadpeek/.env.production
LOG=/opt/leadpeek/scripts/_watchdog_state/supabase_keepalive.log

mkdir -p "$(dirname "$LOG")"

strip_quotes() { sed -e 's/^["'\'']//' -e 's/["'\'']$//'; }
URL=$(grep '^NEXT_PUBLIC_SUPABASE_URL=' "$ENV_FILE" | head -1 | cut -d= -f2- | strip_quotes)
KEY=$(grep '^NEXT_PUBLIC_SUPABASE_ANON_KEY=' "$ENV_FILE" | head -1 | cut -d= -f2- | strip_quotes)

send_alert() {
    local subject="$1"
    local body="$2"
    printf '%s' "$body" | docker exec -i \
        -e KA_SUBJECT="$subject" \
        leadpeek-backend-1 python - <<'PYEOF' >> "$LOG" 2>&1 || true
import os, smtplib, ssl, sys
from email.mime.text import MIMEText
host = os.getenv("SMTP_HOST")
port = int(os.getenv("SMTP_PORT", "587"))
user = os.getenv("SMTP_USER")
pwd  = os.getenv("SMTP_PASS")
sender = os.getenv("SMTP_FROM", "claude@datasnoop.be")
to = os.getenv("SMTP_ALERT_TO")
subj = os.getenv("KA_SUBJECT", "[DataSnoop] Supabase keepalive")
if not (host and user and pwd and to):
    print("missing SMTP config", file=sys.stderr); sys.exit(1)
m = MIMEText(sys.stdin.read(), "plain", "utf-8")
m["Subject"] = subj
m["From"] = f"DataSnoop Watchdog <{sender}>"
m["To"] = to
ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
with smtplib.SMTP(host, port, timeout=20) as s:
    s.ehlo("datasnoop-backend"); s.starttls(context=ctx); s.ehlo("datasnoop-backend")
    s.login(user, pwd); s.sendmail(sender, [to], m.as_string())
print(f"alert sent: {subj}")
PYEOF
}

if [[ -z "$URL" || -z "$KEY" ]]; then
    echo "[$(date -Is)] FAIL: missing NEXT_PUBLIC_SUPABASE_URL or NEXT_PUBLIC_SUPABASE_ANON_KEY in $ENV_FILE" >> "$LOG"
    send_alert "[DataSnoop] Supabase keepalive FAILED (config)" \
        "supabase_keepalive.sh could not read NEXT_PUBLIC_SUPABASE_URL or NEXT_PUBLIC_SUPABASE_ANON_KEY from $ENV_FILE. Project will auto-pause after 7 days of inactivity, breaking login."
    exit 1
fi

CODE=$(curl -s -o /dev/null -w '%{http_code}' \
    -H "apikey: $KEY" \
    -H "Authorization: Bearer $KEY" \
    --max-time 30 \
    "$URL/rest/v1/")

# For activity-tracking purposes, ANY HTTP response from Supabase counts —
# the request reached their gateway, was logged, and resets the inactivity
# timer. We only treat curl-level failures (000 = couldn't connect/DNS/
# timeout) and 5xx server errors as actionable failures.
if [[ "$CODE" == "000" || "$CODE" =~ ^5 ]]; then
    echo "[$(date -Is)] FAIL: HTTP $CODE from /rest/v1/" >> "$LOG"
    send_alert "[DataSnoop] Supabase keepalive FAILED (HTTP $CODE)" \
        "Supabase keepalive could not reach $URL/rest/v1/ (HTTP $CODE). If this persists, the project will auto-pause after 7 days of inactivity, breaking login for all users."
    exit 1
fi

echo "[$(date -Is)] OK: HTTP $CODE from /rest/v1/" >> "$LOG"
