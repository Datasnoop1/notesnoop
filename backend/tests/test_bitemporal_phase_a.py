from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_bitemporal_migration_has_required_views_and_helpers():
    sql = _read("migrations/2026-05-02_bitemporal_phase_a.sql")

    for name in (
        "administrator_current",
        "shareholder_current",
        "participating_interest_current",
        "affiliation_current",
        "administrator_fact",
        "shareholder_fact",
        "participating_interest_fact",
        "affiliation_fact",
        "admins_as_of",
        "shareholders_as_of",
        "participating_interests_as_of",
        "affiliations_as_of",
    ):
        assert name in sql

    assert "(valid_from IS NULL OR valid_from <= CURRENT_DATE)" in sql
    assert "recorded_to IS NULL AND valid_to IS NULL" in sql
    assert "INTERVAL '1 day'" in sql


def test_governance_writer_threads_deposit_date_and_closes_current_rows():
    source = _read("backend/nbb_governance.py")

    assert "deposit_date: date | str | None = None" in source
    assert "_exclusive_end_date" in source
    assert "_insert_bitemporal_unique" in source
    assert "SET recorded_to = NOW()" in source
    assert "_BITEMPORAL_INSERT_COLUMNS" in source


def test_production_reads_do_not_query_bare_fact_tables():
    blocked = (
        r"\bFROM administrator\b",
        r"\bJOIN administrator\b",
        r"\bFROM shareholder\b",
        r"\bJOIN shareholder\b",
        r"\bFROM participating_interest\b",
        r"\bJOIN participating_interest\b",
        r"\bFROM affiliation\b",
        r"\bJOIN affiliation\b",
    )
    allowed_bare_fact_reads = {
        # Temporary find-similar hotfix; see
        # docs/find-similar-bitemporal-fix-2026-05-02.md for context.
        ("backend/retrieval.py", r"\bFROM shareholder\b"),
        ("backend/retrieval.py", r"\bFROM participating_interest\b"),
    }
    allowed_prefixes = ("backend/tests/", "scripts/test_")
    offenders: list[str] = []

    for root in ("backend", "scripts"):
        for path in (ROOT / root).rglob("*.py"):
            rel = path.relative_to(ROOT).as_posix()
            if rel.startswith(allowed_prefixes):
                continue
            text = path.read_text(encoding="utf-8")
            for pattern in blocked:
                import re

                if re.search(pattern, text):
                    if (rel, pattern) in allowed_bare_fact_reads:
                        continue
                    offenders.append(f"{rel}: {pattern}")

    assert offenders == []
