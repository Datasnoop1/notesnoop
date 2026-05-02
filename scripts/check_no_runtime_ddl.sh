#!/usr/bin/env bash
set -euo pipefail

pattern='^[[:space:]]*(CREATE[[:space:]]+(UNIQUE[[:space:]]+)?(TABLE|INDEX|SCHEMA|EXTENSION)|CREATE[[:space:]]+MATERIALIZED[[:space:]]+VIEW|CREATE[[:space:]]+FOREIGN[[:space:]]+TABLE|ALTER[[:space:]]+TABLE|DROP[[:space:]]+(TABLE|INDEX))[[:space:]]'

tmp="$(mktemp)"
filtered="$(mktemp)"
trap 'rm -f "$tmp" "$filtered"' EXIT

git grep -n -I -E "$pattern" -- backend scripts src \
  ':(exclude)migrations/**' \
  ':(exclude)src/schema.sql' > "$tmp" || true

if grep -v 'ALLOW-RUNTIME-DDL:' "$tmp" > "$filtered"; then
  echo "Runtime DDL found outside migrations/src/schema.sql:" >&2
  cat "$filtered" >&2
  echo >&2
  echo "Move schema changes to migrations/ or add an operator-approved ALLOW-RUNTIME-DDL waiver." >&2
  exit 1
fi

echo "No unwaived runtime DDL found."
