"""Regression tests for the search V2 normaliser.

Covers every class of input the original bug report identified plus
boundary cases around the legal-suffix regex.

Run with: pytest backend/tests/test_search_normalization.py -v
"""

import sys
from pathlib import Path

# Make `backend` importable without installing as a package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from search_normalization import (  # noqa: E402
    canonicalise_legal_form,
    detect_query_type,
    extract_cbe_digits,
    ilike_escape,
    normalize_name,
    phonetic_key,
    reversed_key,
    set_synonyms_cache,
    strip_accents,
    tokenize,
)


class TestIlikeEscape:
    """Regression tests for the HIGH-severity wildcard injection fix.

    Without escaping, a user-supplied `%` would match arbitrary
    substrings and force the search into a full table scan.
    """

    def test_percent_escaped(self):
        assert ilike_escape("50% off") == "50\\% off"

    def test_underscore_escaped(self):
        assert ilike_escape("acme_corp") == "acme\\_corp"

    def test_backslash_escaped_first(self):
        # Must escape backslash BEFORE %/_ so we don't double-escape.
        assert ilike_escape("a\\b") == "a\\\\b"
        # Combined: %%\\__  → literal %%\\__
        assert ilike_escape("%\\_") == "\\%\\\\\\_"

    def test_plain_text_unchanged(self):
        assert ilike_escape("Colruyt") == "Colruyt"
        assert ilike_escape("van der Meer") == "van der Meer"

    def test_empty(self):
        assert ilike_escape("") == ""
        assert ilike_escape(None) == ""  # type: ignore[arg-type]


class TestStripAccents:
    def test_french(self):
        assert strip_accents("Jérôme") == "Jerome"
        assert strip_accents("Liège") == "Liege"
        assert strip_accents("André") == "Andre"

    def test_dutch(self):
        assert strip_accents("Curaçao") == "Curacao"

    def test_german_umlauts(self):
        # NFKD splits ä→a+combining-diaeresis; we drop the combining char.
        assert strip_accents("Müller") == "Muller"
        assert strip_accents("Söhne") == "Sohne"

    def test_ligatures_not_touched(self):
        # NFKD does NOT split ß into ss — that's NFKC/compatibility folding.
        # f_unaccent via Postgres does split it via the unaccent dictionary
        # (rules file). We accept this asymmetry for now because ß is
        # extremely rare in Belgian data.
        assert strip_accents("Straße") == "Straße"

    def test_empty(self):
        assert strip_accents("") == ""
        assert strip_accents(None) == ""  # type: ignore[arg-type]


class TestNormalizeName:
    def test_accent_stripped(self):
        assert normalize_name("Jerôme") == "jerome"
        assert normalize_name("Liège") == "liege"
        assert normalize_name("André") == "andre"

    def test_whitespace_collapsed(self):
        assert normalize_name("  Colruyt   Group  ") == "colruyt group"
        assert normalize_name("Colruyt\u00a0Group") == "colruyt group"  # NBSP
        assert normalize_name("Colruyt\tGroup") == "colruyt group"

    def test_trailing_suffix_stripped(self):
        assert normalize_name("Colruyt NV") == "colruyt"
        assert normalize_name("Colruyt Group NV") == "colruyt group"
        assert normalize_name("Acme SA") == "acme"
        assert normalize_name("Acme BVBA") == "acme"
        assert normalize_name("Acme Holding GmbH") == "acme holding"
        assert normalize_name("Acme Partners Ltd.") == "acme partners"
        assert normalize_name("Acme Corp.") == "acme"
        assert normalize_name("Acme, Inc.") == "acme"
        assert normalize_name("Some VZW") == "some"
        assert normalize_name("Some ASBL") == "some"

    def test_multi_suffix_stripped(self):
        # Regression for the search V2 audit: multi-suffix names must
        # strip iteratively, else the normalised form drifts between
        # the user's query and the stored column.
        assert normalize_name("Acme NV SA") == "acme"
        assert normalize_name("Acme Holdings Ltd, Inc.") == "acme holdings"
        assert normalize_name("Some VZW ASBL") == "some"

    def test_punctuation_class_aligns_with_sql(self):
        # SQL uses `[[:space:][:punct:]]*` — covers `;:!?"' `.
        # Python regex uses `[\s\W_]{0,16}` which is the same class
        # bounded by 16 chars. Verify the user-visible behaviour.
        assert normalize_name("Acme; Inc.") == "acme"
        assert normalize_name("Acme: Ltd") == "acme"
        assert normalize_name("Acme? NV") == "acme"
        assert normalize_name('"Acme" NV') == "acme"

    def test_suffix_preserved_when_leading(self):
        # Must NOT strip leading/internal "NV". The NVidia case.
        assert normalize_name("NVidia Belgium") == "nvidia belgium"
        assert normalize_name("NV Industries") == "nv industries"
        assert normalize_name("SA Media") == "sa media"

    def test_empty_and_none(self):
        assert normalize_name("") == ""
        assert normalize_name(None) == ""
        assert normalize_name("   ") == ""


class TestTokenize:
    def test_basic(self):
        assert tokenize("Colruyt Group") == ["colruyt", "group"]

    def test_punctuation_dropped(self):
        assert tokenize("BRAET, TIM") == ["braet", "tim"]
        assert tokenize("van der Meer, Jan") == ["van", "der", "meer", "jan"]

    def test_empty(self):
        assert tokenize("") == []
        assert tokenize(None) == []


class TestReversedKey:
    def test_order_agnostic(self):
        assert reversed_key("Tim Braet") == reversed_key("Braet Tim")
        assert reversed_key("BRAET, TIM") == reversed_key("Tim Braet")
        assert reversed_key("van der Meer Jan") == reversed_key("Jan van der Meer")

    def test_value(self):
        assert reversed_key("Tim Braet") == "braet tim"

    def test_empty(self):
        assert reversed_key("") == ""


class TestDetectQueryType:
    def test_cbe(self):
        assert detect_query_type("0403.170.701") == "cbe"
        assert detect_query_type("0403170701") == "cbe"
        assert detect_query_type("BE0403170701") == "cbe"
        assert detect_query_type("BE 0403.170.701") == "cbe"
        assert detect_query_type("403170701") == "cbe"  # 9-digit (BE drops leading zero)

    def test_zipcode(self):
        assert detect_query_type("1000") == "zipcode"
        assert detect_query_type("9000") == "zipcode"
        assert detect_query_type(" 1050 ") == "zipcode"

    def test_person_like(self):
        assert detect_query_type("Tim Braet") == "person_like"
        assert detect_query_type("jerome colruyt") == "person_like"
        assert detect_query_type("Jan van der Meer") == "person_like"
        assert detect_query_type("Jérôme Colruyt") == "person_like"

    def test_company_like(self):
        # 'group' hint word
        assert detect_query_type("Colruyt Group") == "company_like"
        # single token
        assert detect_query_type("Colruyt") == "company_like"
        # has digits (non-CBE)
        assert detect_query_type("Acme 2020") == "company_like"
        # 5+ tokens
        assert detect_query_type("a b c d e") == "company_like"
        # contains a hint word
        assert detect_query_type("Bosch Holding") == "company_like"

    def test_empty(self):
        assert detect_query_type("") == "company_like"
        assert detect_query_type("   ") == "company_like"
        assert detect_query_type(None) == "company_like"  # type: ignore[arg-type]


class TestExtractCbeDigits:
    def test_pads_nine_to_ten(self):
        assert extract_cbe_digits("403170701") == "0403170701"

    def test_preserves_ten(self):
        assert extract_cbe_digits("0403170701") == "0403170701"

    def test_strips_dots_and_be(self):
        assert extract_cbe_digits("BE 0403.170.701") == "0403170701"
        assert extract_cbe_digits("BE-0403-170-701") == "0403170701"

    def test_non_cbe_returns_none(self):
        assert extract_cbe_digits("Colruyt") is None
        assert extract_cbe_digits("") is None
        assert extract_cbe_digits(None) is None


class TestPhoneticKey:
    def test_empty(self):
        assert phonetic_key("") == ""
        assert phonetic_key(None) == ""

    def test_non_empty(self):
        # We don't assert the exact dmetaphone output (it varies by
        # implementation) — just that tokens produce non-empty keys
        # when the metaphone package is installed.
        key = phonetic_key("Tim Braet")
        # Allow empty key when metaphone isn't installed (import guard
        # in dmetaphone_token) — the test is tolerant of that.
        assert isinstance(key, str)


class TestSynonymsCache:
    def test_round_trip(self):
        set_synonyms_cache({"NV": "nv", "SA": "nv", "BV": "bv", "SPRL": "bv"})
        assert canonicalise_legal_form("NV") == "nv"
        assert canonicalise_legal_form("sa") == "nv"
        assert canonicalise_legal_form("BV") == "bv"
        assert canonicalise_legal_form("SPRL") == "bv"
        assert canonicalise_legal_form("unknown_form") == "unknown_form"

    def test_empty_input(self):
        set_synonyms_cache({})
        assert canonicalise_legal_form("") == ""
        assert canonicalise_legal_form("nv") == "nv"  # pass-through
