#!/bin/bash
# Scrub credentials and connection-string secrets from a journalctl-style
# log stream. Reads stdin, writes scrubbed text to stdout.
#
# Used by deploy/leadpeek-backup-failure.service before piping the log into
# the alert email body, so a libpq error like
#     PGPASSWORD=hunter2 connection failed
# does not leak via SMTP. Redacts the VALUE, not just the key — pattern
# matches KEY=value / KEY: value pairs and basic-auth URIs.
#
# Written to be portable across GNU sed (Ubuntu prod) and BSD/POSIX seds
# (occasional self-test environments). Each rule is a separate -e to avoid
# embedded #-comments which not all seds tolerate.

set -uo pipefail

sed -E \
    -e 's/(password|PGPASSWORD|SMTP_PASS|PGPASS|api[_-]?key|secret|token)([[:space:]]*[=:][[:space:]]*)[^[:space:]]+/\1\2REDACTED/Ig' \
    -e 's/(authorization[[:space:]]*:[[:space:]]*)?(bearer)([[:space:]]+)[^[:space:]]+/\1\2\3REDACTED/Ig' \
    -e 's,((postgres|postgresql|mysql|amqp|https?|ftp)://)[^:@[:space:]/]+:[^@[:space:]]*@,\1REDACTED@,Ig' \
    -e 's/(user|username|usr)([[:space:]]*=[[:space:]]*)[^[:space:]]+/\1\2REDACTED/Ig'
