#!/usr/bin/env bash
# Search V2 smoke tests — run against staging (or prod) after deploy.
# Exits non-zero if any check fails. Each check prints PASS / FAIL
# plus the query, the observed bucket sizes, and the top result name.
#
# Usage:
#   BASE_URL=http://staging.datasnoop.be:8080 ./scripts/smoke_search_v2.sh
#   BASE_URL=https://datasnoop.be ./scripts/smoke_search_v2.sh
#
# Requires: curl, jq.

set -u
BASE_URL="${BASE_URL:-http://localhost:8000}"
FAILURES=0
TESTS=0

bold() { printf '\033[1m%s\033[0m' "$1"; }
red()  { printf '\033[31m%s\033[0m' "$1"; }
green(){ printf '\033[32m%s\033[0m' "$1"; }

# Runs a /api/companies/search query and asserts the given bucket has
# at least min_count results.  Usage:
#   check_companies "query" bucket min_count "description"
check_companies() {
  local q="$1" bucket="$2" min="$3" desc="$4"
  TESTS=$((TESTS + 1))
  local encoded
  encoded=$(python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1]))' "$q")
  local json
  if ! json=$(curl -fsS --max-time 8 "$BASE_URL/api/companies/search?q=$encoded" 2>/dev/null); then
    echo "$(red FAIL) [$desc] curl failed for q=$q"
    FAILURES=$((FAILURES + 1)); return
  fi
  local commercial nonprofit top_name
  commercial=$(echo "$json" | jq -r '.commercial | length')
  nonprofit=$(echo "$json" | jq -r '.nonprofit_or_public | length')
  top_name=$(echo "$json" | jq -r ".${bucket}[0].name // \"<none>\"")
  local count
  if [ "$bucket" = "commercial" ]; then count=$commercial; else count=$nonprofit; fi
  if [ "$count" -ge "$min" ]; then
    echo "$(green PASS) [$desc] q='$q' commercial=$commercial nonprofit=$nonprofit top=$top_name"
  else
    echo "$(red  FAIL) [$desc] q='$q' expected ≥$min in $bucket, got $count (top=$top_name)"
    FAILURES=$((FAILURES + 1))
  fi
}

check_suggest() {
  local q="$1" field="$2" min="$3" desc="$4"
  TESTS=$((TESTS + 1))
  local encoded json count
  encoded=$(python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1]))' "$q")
  if ! json=$(curl -fsS --max-time 4 "$BASE_URL/api/search/suggest?q=$encoded" 2>/dev/null); then
    echo "$(red FAIL) [$desc] suggest curl failed for q=$q"
    FAILURES=$((FAILURES + 1)); return
  fi
  if [ "$field" = "cbe_match" ]; then
    if [ "$(echo "$json" | jq -r '.cbe_match | tostring')" != "null" ]; then
      echo "$(green PASS) [$desc] q='$q' suggest.cbe_match present"
    else
      echo "$(red  FAIL) [$desc] q='$q' suggest.cbe_match null"
      FAILURES=$((FAILURES + 1))
    fi
  else
    count=$(echo "$json" | jq -r ".${field} | length")
    if [ "$count" -ge "$min" ]; then
      echo "$(green PASS) [$desc] q='$q' suggest.$field=$count"
    else
      echo "$(red  FAIL) [$desc] q='$q' expected ≥$min in suggest.$field, got $count"
      FAILURES=$((FAILURES + 1))
    fi
  fi
}

check_people() {
  local q="$1" min="$2" desc="$3"
  TESTS=$((TESTS + 1))
  local encoded json count
  encoded=$(python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1]))' "$q")
  if ! json=$(curl -fsS --max-time 8 "$BASE_URL/api/people/search?q=$encoded" 2>/dev/null); then
    echo "$(red FAIL) [$desc] people curl failed for q=$q"
    FAILURES=$((FAILURES + 1)); return
  fi
  count=$(echo "$json" | jq -r 'length')
  if [ "$count" -ge "$min" ]; then
    echo "$(green PASS) [$desc] q='$q' people=$count"
  else
    echo "$(red  FAIL) [$desc] q='$q' expected ≥$min people, got $count"
    FAILURES=$((FAILURES + 1))
  fi
}

echo "Smoke-testing $BASE_URL"
echo ""

# ---------------------------------------------------------------------------
# Company search — commercial
# ---------------------------------------------------------------------------
check_companies "Colruyt"                    commercial 1 "commercial-basic"
check_companies "Colruyt NV"                 commercial 1 "commercial-with-NV-suffix"
check_companies "Colruyt SA"                 commercial 1 "legal-form-synonym-SA"
check_companies "Colruyt  Group  NV"         commercial 1 "collapses-double-space"
check_companies "NVidia Belgium"             commercial 0 "leading-NV-not-stripped"
check_companies "Liège"                      commercial 1 "accent-liege"
check_companies "Liege"                      commercial 1 "no-accent-liege"
check_companies "Rue Neuve"                  commercial 1 "address-street"
check_companies "1000"                       commercial 1 "address-zipcode"

# ---------------------------------------------------------------------------
# Company search — nonprofit / public
# ---------------------------------------------------------------------------
check_companies "VZW"                        nonprofit_or_public 1 "nonprofit-vzw-bucket"
check_companies "ASBL"                       nonprofit_or_public 1 "nonprofit-asbl-bucket"
check_companies "Stad Antwerpen"             nonprofit_or_public 1 "public-city"
check_companies "Rode Kruis"                 nonprofit_or_public 0 "rode-kruis-nonprofit"

# ---------------------------------------------------------------------------
# CBE / VAT short-circuit
# ---------------------------------------------------------------------------
check_companies "0400378485"                 commercial 1 "cbe-canonical"
check_companies "BE 0400.378.485"            commercial 1 "cbe-be-prefix-dots"
check_companies "400378485"                  commercial 1 "cbe-9-digit"

# ---------------------------------------------------------------------------
# People search — order/accent/suffix
# ---------------------------------------------------------------------------
check_people "Jérôme"                        0 "people-accent"
check_people "Jerome"                        0 "people-no-accent"
check_people "van der Meer Jan"              0 "people-particle-order-A"
check_people "Jan van der Meer"              0 "people-particle-order-B"

# ---------------------------------------------------------------------------
# Autocomplete
# ---------------------------------------------------------------------------
check_suggest "Col"                          companies 1 "suggest-company-prefix"
check_suggest "0400"                         cbe_match _ "suggest-cbe"
check_suggest "Rue"                          addresses 0 "suggest-address"

# ---------------------------------------------------------------------------
# Pathological inputs — must not 500
# ---------------------------------------------------------------------------
check_companies "%%%"                        commercial 0 "punct-only"
check_companies "a'b"                        commercial 0 "single-quote"
check_companies "   "                        commercial 0 "whitespace-only"

echo ""
echo "------------------------------------------------------------------"
if [ "$FAILURES" -eq 0 ]; then
  echo "$(green "All $TESTS smoke tests passed.")"
  exit 0
else
  echo "$(red "$FAILURES of $TESTS smoke tests failed.")"
  exit 1
fi
