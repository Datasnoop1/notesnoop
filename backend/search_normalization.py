"""Search V2 canonical normalisation.

Python reference implementation matching the SQL functions defined in
`migrations/2026-04-24_search_v2.sql` EXACTLY. If you change one, change
the other. Cross-checked by `backend/tests/test_search_normalization.py`.

The query-type router drives the backend search dispatcher: we detect
CBE / VAT / zipcode inputs up front and short-circuit to exact lookups
instead of letting them pollute the text index path.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Literal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Trailing legal-form suffix regex. ANCHORED with $ so it only fires at
# the end of the string — "NVidia" stays "nvidia", not "idia". Extended
# with foreign forms users paste from CRMs (GmbH, Ltd, Inc, SAS, SARL).
# Must match the SQL regex in search_normalize() exactly.
# ---------------------------------------------------------------------------
# Surrounding character class matches the SQL side's `[[:space:][:punct:]]*`
# as closely as possible. Python's `\W` = non-word (includes punctuation
# AND unicode symbols); combined with whitespace + underscore it covers
# POSIX punct well enough for our purposes. The character class is
# ungreedy-bounded to 16 chars to avoid a theoretical ReDoS on crafted
# pathological input.
_SUFFIX_RE = re.compile(
    r"[\s\W_]{0,16}"
    r"("
        r"nv|sa|bvba|sprl|bv|srl|cvba|scrl|vof|snc|se|scs|gcv|"
        r"comm\.?\s*v|scomm|asbl|vzw|aisbl|ivzw|"
        r"gmbh|ag|ltd|inc|sas|sarl|llc|plc|corp|spa|kg|ohg|ug|eurl"
    r")"
    r"[\s\W_]{0,16}$",
    re.IGNORECASE,
)

_WHITESPACE_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)

# Query-type detection. CBE tolerates dots, spaces, dashes, and an
# optional "BE" prefix anywhere along the number: "BE 0403.170.701",
# "0403-170-701", "403170701" (9-digit — KBO drops the leading zero on
# display), "0403170701". We strip non-digits and validate length.
_CBE_PREFIX_STRIP_RE = re.compile(r"^\s*BE[\s.\-]*", re.IGNORECASE)
_CBE_NONDIGIT_RE = re.compile(r"[\s.\-]")
_CBE_ALL_DIGITS_RE = re.compile(r"^\d{9,10}$")
_ZIPCODE_RE = re.compile(r"^\s*(\d{4})\s*$")

# Words that signal "this is probably a company name, not a person".
# Used by detect_query_type's person-vs-company heuristic.
_COMPANY_HINT_WORDS = frozenset({
    "group", "groep", "holding", "invest", "investments", "capital",
    "partners", "consulting", "services", "solutions", "international",
    "europe", "benelux", "belgium", "belgique", "trading", "industries",
    "systems", "technology", "technologies", "pharma", "labs",
})


def strip_accents(s: str) -> str:
    """NFKD decomposition + drop combining chars. 'Jerôme' → 'Jerome'."""
    if not s:
        return ""
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalize_name(name: str | None) -> str:
    """Canonical query/name normaliser — matches SQL `search_normalize`.

    Steps:
      1. NFKD strip accents
      2. strip trailing legal suffix (NV/SA/…/GmbH/Ltd/…)
      3. lowercase
      4. collapse whitespace
    """
    if not name:
        return ""
    s = strip_accents(name)
    # Loop the suffix regex so "Acme NV SA" strips to "Acme", not
    # "Acme NV". Cap at 4 iterations to bound worst-case time.
    for _ in range(4):
        new_s = _SUFFIX_RE.sub("", s)
        if new_s == s:
            break
        s = new_s
    # Users paste quoted names from CRMs and spreadsheets ("Acme" NV).
    # Legal-suffix stripping leaves the wrapper punctuation behind, which
    # breaks exact/prefix lookup even though the stored KBO name is plain.
    s = re.sub(r"^[\s\W_]+|[\s\W_]+$", "", s)
    s = s.lower()
    s = _WHITESPACE_RE.sub(" ", s).strip()
    return s


def tokenize(name: str | None) -> list[str]:
    """Split a normalised name into a stable token list."""
    if not name:
        return []
    cleaned = _PUNCT_RE.sub(" ", normalize_name(name))
    return [t for t in cleaned.split() if t]


def reversed_key(name: str | None) -> str:
    """Order-insensitive key: sorted tokens joined by space.

    "Tim Braet", "Braet Tim", and "BRAET, TIM" all yield "braet tim".
    Matches SQL search_name_reversed().
    """
    tokens = sorted(tokenize(name))
    return " ".join(tokens)


QueryType = Literal["cbe", "zipcode", "person_like", "company_like"]


def detect_query_type(q: str) -> QueryType:
    """Route the query to the right backend path.

    - `cbe`         — Belgian enterprise number (with/without BE/dots).
    - `zipcode`     — exactly 4 digits.
    - `person_like` — 2-4 non-digit alpha tokens, no company hint words.
    - `company_like`— everything else (default).
    """
    if not q:
        return "company_like"
    qs = q.strip()
    if not qs:
        return "company_like"
    if extract_cbe_digits(qs) is not None:
        return "cbe"
    if _ZIPCODE_RE.match(qs):
        return "zipcode"
    # Digits elsewhere → company-like (names don't usually have digits).
    if any(ch.isdigit() for ch in qs):
        return "company_like"
    tokens = tokenize(qs)
    if not tokens:
        return "company_like"
    if (
        2 <= len(tokens) <= 4
        and not any(t in _COMPANY_HINT_WORDS for t in tokens)
        and all(len(t) >= 2 for t in tokens)
    ):
        return "person_like"
    return "company_like"


def extract_cbe_digits(q: str | None) -> str | None:
    """Pull the 10-digit CBE out of a user input. None if not CBE-like.

    Accepts: "0403170701", "0403.170.701", "403170701" (missing leading
    zero), "BE0403170701", "BE 0403.170.701", "BE-0403-170-701".
    """
    if not q:
        return None
    s = _CBE_PREFIX_STRIP_RE.sub("", q.strip())
    s = _CBE_NONDIGIT_RE.sub("", s)
    if _CBE_ALL_DIGITS_RE.match(s):
        # KBO canonical form is 10 digits with leading zero.
        return s.zfill(10)
    return None


def ilike_escape(s: str) -> str:
    """Escape `%`, `_`, `\\` so a user-supplied substring is matched literally.

    Callers wrap the returned value in `%{…}%` for ILIKE; the matching SQL
    must use `ESCAPE '\\'`. Without this, a crafted query like `"%"` makes
    the search fan out to a full table scan.
    """
    if not s:
        return ""
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def dmetaphone_token(tok: str) -> str:
    """Double Metaphone primary key for one token. Identity fallback.

    The SQL side uses dmetaphone() from the `fuzzystrmatch` extension.
    The `metaphone` PyPI package implements the same algorithm, so
    query-side keys should match stored keys byte-for-byte.
    """
    if not tok:
        return ""
    try:
        from metaphone import doublemetaphone
        primary, _ = doublemetaphone(tok)
        return (primary or tok).strip()
    except ImportError:
        # If the `metaphone` package is missing we degrade to identity
        # matching (never match phonetically). Search still works via
        # trigram + token-AND; logging this once on first call is enough.
        logger.warning(
            "metaphone package not installed — phonetic search disabled. "
            "Install with: pip install metaphone==0.6"
        )
        return tok


def phonetic_key(name: str | None) -> str:
    """Space-joined dmetaphone keys per token, matching SQL search_phonetic_key."""
    tokens = tokenize(name)
    if not tokens:
        return ""
    return " ".join(dmetaphone_token(t) for t in tokens).strip()


# ---------------------------------------------------------------------------
# Synonym cache — loaded once at startup by backend/main.py lifespan from
# `legal_form_synonyms`. Degrades gracefully to empty dict if the
# migration hasn't run yet.
# ---------------------------------------------------------------------------

_SYNONYMS_CACHE: dict[str, str] = {}


def set_synonyms_cache(data: dict[str, str]) -> None:
    """Populate the module-level synonyms cache from DB rows."""
    global _SYNONYMS_CACHE
    _SYNONYMS_CACHE = {
        (k or "").lower(): (v or "").lower()
        for k, v in (data or {}).items()
        if k and v
    }


def canonicalise_legal_form(token: str) -> str:
    """Map any legal-form alias to its canonical key. No-op if not a form."""
    if not token:
        return ""
    return _SYNONYMS_CACHE.get(token.lower(), token)
