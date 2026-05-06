#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

read_env_key() {
  local file="$1"
  local key="$2"
  [[ -f "$file" ]] || return 1
  awk -v wanted="$key" '
    BEGIN { FS = "=" }
    $1 == wanted {
      sub(/^[^=]*=/, "", $0)
      gsub(/^[ \t]+|[ \t]+$/, "", $0)
      gsub(/^'\''|'\''$/, "", $0)
      gsub(/^"|"$/, "", $0)
      print
      exit 0
    }
  ' "$file"
}

db_url="${MIGRATE_PROD_DATABASE_URL:-}"
if [[ -z "$db_url" ]]; then
  for env_file in /opt/leadpeek/.env.production .env.production; do
    for env_key in MIGRATE_PROD_DATABASE_URL PROD_DATABASE_URL HETZNER_PG_URL DATABASE_URL; do
      value="$(read_env_key "$env_file" "$env_key" || true)"
      if [[ -n "$value" ]]; then
        db_url="$value"
        break 2
      fi
    done
  done
fi

if [[ -z "$db_url" ]]; then
  for env_key in MIGRATE_PROD_DATABASE_URL PROD_DATABASE_URL HETZNER_PG_URL DATABASE_URL; do
    value="${!env_key:-}"
    if [[ -n "$value" ]]; then
      db_url="$value"
      break
    fi
  done
fi

if [[ -z "$db_url" ]]; then
  echo "MIGRATE_PROD_DATABASE_URL / PROD_DATABASE_URL / HETZNER_PG_URL / DATABASE_URL is not configured" >&2
  exit 1
fi

pgpass_file="$(mktemp)"
conn_env_file="$(mktemp)"
chmod 600 "$pgpass_file" "$conn_env_file"
cleanup() {
  rm -f "$pgpass_file" "$conn_env_file"
}
trap cleanup EXIT

parser_env="$(mktemp)"
chmod 600 "$parser_env"
printf 'STAGE_D_RAW_DB_URL=%s\nSTAGE_D_PGPASS_FILE=%s\n' "$db_url" "$pgpass_file" > "$parser_env"
env -i PATH="${PATH:-/usr/bin:/bin}" HOME="${HOME:-/root}" python3 - "$parser_env" <<'PY' > "$conn_env_file"
import os
import shlex
import sys
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse


def pgpass_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace(":", "\\:")


env_file = Path(sys.argv[1])
values = {}
for line in env_file.read_text(encoding="utf-8").splitlines():
    key, value = line.split("=", 1)
    values[key] = value
env_file.unlink(missing_ok=True)

raw_url = values["STAGE_D_RAW_DB_URL"].replace("host.docker.internal", "127.0.0.1")
pgpass_file = Path(values["STAGE_D_PGPASS_FILE"])
parsed = urlparse(raw_url)

host = parsed.hostname or "127.0.0.1"
port = str(parsed.port or 5432)
database = unquote((parsed.path or "").lstrip("/"))
user = unquote(parsed.username or "")
password = unquote(parsed.password or "")
query = parse_qs(parsed.query)

if not database or not user:
    raise SystemExit("Database URL is missing database or user")

pgpass_file.write_text(
    f"{pgpass_escape(host)}:{pgpass_escape(port)}:{pgpass_escape(database)}:{pgpass_escape(user)}:{pgpass_escape(password)}\n",
    encoding="utf-8",
)
pgpass_file.chmod(0o600)

exports = {
    "PGHOST": host,
    "PGPORT": port,
    "PGDATABASE": database,
    "PGUSER": user,
    "PGPASSFILE": str(pgpass_file),
}
if query.get("sslmode"):
    exports["PGSSLMODE"] = query["sslmode"][0]

for key, value in exports.items():
    print(f"export {key}={shlex.quote(value)}")
PY

rm -f "$parser_env"
unset db_url value parser_env STAGE_D_RAW_DB_URL STAGE_D_PGPASS_FILE
unset MIGRATE_PROD_DATABASE_URL PROD_DATABASE_URL HETZNER_PG_URL DATABASE_URL
# shellcheck disable=SC1090
source "$conn_env_file"

psql "$@"
