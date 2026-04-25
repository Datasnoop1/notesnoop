"""Helpers for extracting and storing governance rows from NBB filings."""

from __future__ import annotations

from typing import Any


_ADMIN_COLUMNS = (
    "enterprise_number",
    "deposit_key",
    "fiscal_year",
    "person_type",
    "name",
    "role",
    "identifier",
    "mandate_start",
    "mandate_end",
    "representative_name",
)

_SHAREHOLDER_COLUMNS = (
    "enterprise_number",
    "deposit_key",
    "fiscal_year",
    "shareholder_type",
    "name",
    "identifier",
    "address",
    "shares_held",
    "ownership_pct",
)

_PI_COLUMNS = (
    "enterprise_number",
    "deposit_key",
    "fiscal_year",
    "name",
    "identifier",
    "address",
    "country",
    "ownership_pct",
    "equity_value",
    "net_result",
)

_AFFILIATION_COLUMNS = (
    "person_name",
    "enterprise_number",        # Company 2: the company Person X represents
    "via_enterprise_number",    # Company 1: where the link was observed
    "via_deposit_key",
    "fiscal_year",
    "affiliation_type",
    "person_identifier",
)


def _clean_cbe(raw: Any) -> str | None:
    """NBB returns CBEs sometimes as '0123.456.789'; canonicalise to 10 digits.

    Returns None for empty/missing values so we never insert a placeholder
    enterprise_number that would silently widen the search graph.
    """
    if raw in (None, ""):
        return None
    digits = "".join(ch for ch in str(raw) if ch.isdigit())
    if len(digits) != 10:
        return None
    return digits


def _pick(d: dict[str, Any] | None, *keys: str) -> Any:
    if not isinstance(d, dict):
        return None
    for key in keys:
        value = d.get(key)
        if value not in (None, ""):
            return value
    return None


def _as_float(raw: Any) -> float | None:
    if raw in (None, ""):
        return None
    try:
        return float(str(raw).replace(",", ".").strip())
    except (TypeError, ValueError):
        return None


def _person_name(person: dict[str, Any] | None) -> str:
    person = person or {}
    first = _pick(person, "FirstName", "firstName") or ""
    last = _pick(person, "LastName", "lastName") or ""
    return f"{first} {last}".strip()


def _dedupe(rows: list[tuple], key_indexes: tuple[int, ...]) -> list[tuple]:
    seen: set[tuple[Any, ...]] = set()
    unique_rows: list[tuple] = []
    for row in rows:
        key = tuple(row[idx] for idx in key_indexes)
        if key in seen:
            continue
        seen.add(key)
        unique_rows.append(row)
    return unique_rows


def _extract_pct(holdings: Any) -> float | None:
    if not isinstance(holdings, list):
        return None
    for holding in holdings:
        pct = _as_float(_pick(holding, "PercentageDirectlyHeld", "percentageDirectlyHeld"))
        if pct is not None:
            return pct * 100
    return None


def extract_governance_snapshot(
    cbe: str,
    deposit_key: str,
    fiscal_year: int | str | None,
    filing_json: dict[str, Any] | None,
) -> dict[str, list[tuple]]:
    """Return governance rows parsed from one NBB filing."""
    if not deposit_key or not isinstance(filing_json, dict):
        return {
            "administrators": [],
            "shareholders": [],
            "participating_interests": [],
            "affiliations": [],
        }

    fiscal_year_text = str(fiscal_year) if fiscal_year not in (None, "") else None
    cbe_clean = _clean_cbe(cbe)
    admin_rows: list[tuple] = []
    shareholder_rows: list[tuple] = []
    pi_rows: list[tuple] = []
    affiliation_rows: list[tuple] = []

    admins = filing_json.get("Administrators") or filing_json.get("administrators") or {}

    natural_people = admins.get("NaturalPersons") or admins.get("naturalPersons") or []
    for person in natural_people:
        person_data = person.get("Person") or person.get("person") or {}
        name = _person_name(person_data)
        if not name:
            continue
        mandates = person.get("Mandates") or person.get("mandates") or []
        for mandate in mandates:
            dates = mandate.get("MandateDates") or mandate.get("mandateDates") or {}
            admin_rows.append((
                cbe,
                deposit_key,
                fiscal_year_text,
                "natural",
                name,
                _pick(mandate, "FunctionMandate", "functionMandate") or "",
                None,
                _pick(dates, "StartDate", "startDate"),
                _pick(dates, "EndDate", "endDate"),
                None,
            ))

    legal_people = admins.get("LegalPersons") or admins.get("legalPersons") or []
    for legal_person in legal_people:
        entity = legal_person.get("Entity") or legal_person.get("entity") or {}
        name = _pick(entity, "Name", "name") or ""
        if not name:
            continue
        legal_identifier_raw = _pick(entity, "Identifier", "identifier")
        affiliated_cbe = _clean_cbe(legal_identifier_raw)
        # Representatives: the natural person(s) standing in for the corporate
        # director. We capture all of them, not just the first, since one
        # legal-person admin may name several permanent reps.
        representatives = (
            legal_person.get("Representatives")
            or legal_person.get("representatives")
            or []
        )
        rep_names: list[str] = []
        for rep in representatives:
            if not isinstance(rep, dict):
                continue
            rep_name = _person_name(rep)
            if rep_name:
                rep_names.append(rep_name)
        # First rep keeps the legacy `representative_name` slot for
        # backward compatibility with any caller still reading that
        # column. The full list lands in `affiliation_rows`.
        legacy_rep_name = rep_names[0] if rep_names else None
        mandates = legal_person.get("Mandates") or legal_person.get("mandates") or []
        for mandate in mandates:
            dates = mandate.get("MandateDates") or mandate.get("mandateDates") or {}
            admin_rows.append((
                cbe,
                deposit_key,
                fiscal_year_text,
                "legal",
                name,
                _pick(mandate, "FunctionMandate", "functionMandate") or "",
                legal_identifier_raw,
                _pick(dates, "StartDate", "startDate"),
                _pick(dates, "EndDate", "endDate"),
                legacy_rep_name,
            ))
        # Affiliation rows are independent of the per-mandate fan-out:
        # one rep × one corporate-director relationship × one filing.
        # Skip if we can't resolve EITHER side of the link to a clean
        # 10-digit CBE — without both we'd insert junk into
        # via_enterprise_number that no JOIN could ever recover.
        if affiliated_cbe and cbe_clean and affiliated_cbe != cbe_clean:
            for rep_name in rep_names:
                rep_identifier = None
                # Walk the rep dicts again to pull an identifier if the
                # NBB schema happened to expose one (rare).
                for rep in representatives:
                    if not isinstance(rep, dict):
                        continue
                    if _person_name(rep) == rep_name:
                        rep_identifier = _pick(rep, "Identifier", "identifier")
                        break
                affiliation_rows.append((
                    rep_name,
                    affiliated_cbe,
                    cbe_clean,
                    deposit_key,
                    fiscal_year_text,
                    "represents_admin",
                    rep_identifier,
                ))

    interests = filing_json.get("ParticipatingInterests") or filing_json.get("participatingInterests") or []
    if isinstance(interests, list):
        for interest in interests:
            entity = interest.get("Entity") or interest.get("entity") or {}
            name = _pick(entity, "Name", "name") or ""
            if not name:
                continue
            pi_rows.append((
                cbe,
                deposit_key,
                fiscal_year_text,
                name,
                _pick(entity, "Identifier", "identifier"),
                None,
                "BE",
                _extract_pct(
                    interest.get("ParticipatingInterestHeld")
                    or interest.get("participatingInterestHeld")
                    or []
                ),
                None,
                None,
            ))

    shareholders = filing_json.get("Shareholders") or filing_json.get("shareholders") or {}
    entity_shareholders = (
        shareholders.get("EntityShareHolders")
        or shareholders.get("entityShareHolders")
        or []
    )
    for shareholder in entity_shareholders:
        entity = shareholder.get("Entity") or shareholder.get("entity") or {}
        name = _pick(entity, "Name", "name") or ""
        if not name:
            continue
        holdings = (
            shareholder.get("SharesHeld")
            or shareholder.get("sharesHeld")
            or shareholder.get("ParticipatingInterestHeld")
            or shareholder.get("participatingInterestHeld")
            or []
        )
        shareholder_rows.append((
            cbe,
            deposit_key,
            fiscal_year_text,
            "entity",
            name,
            _pick(entity, "Identifier", "identifier"),
            None,
            None,
            _extract_pct(holdings),
        ))

    individual_shareholders = (
        shareholders.get("IndividualShareHolders")
        or shareholders.get("individualShareHolders")
        or []
    )
    for shareholder in individual_shareholders:
        person_data = shareholder.get("Person") or shareholder.get("person") or {}
        name = _person_name(person_data)
        if not name:
            continue
        shareholder_rows.append((
            cbe,
            deposit_key,
            fiscal_year_text,
            "individual",
            name,
            None,
            None,
            None,
            None,
        ))

    return {
        "administrators": _dedupe(admin_rows, (0, 1, 4, 5)),
        "shareholders": _dedupe(shareholder_rows, (0, 1, 4)),
        "participating_interests": _dedupe(pi_rows, (0, 1, 3)),
        # PK is (person_name, enterprise_number, via_enterprise_number,
        # affiliation_type) — same indexes as the table constraint.
        "affiliations": _dedupe(affiliation_rows, (0, 1, 2, 5)),
    }


def _insert_unique(cur, table: str, columns: tuple[str, ...], identity_columns: tuple[str, ...], row: tuple) -> int:
    col_sql = ", ".join(columns)
    value_sql = ", ".join(["%s"] * len(columns))
    identity_sql = " AND ".join(f"{column} IS NOT DISTINCT FROM %s" for column in identity_columns)
    identity_values = tuple(row[columns.index(column)] for column in identity_columns)
    cur.execute(
        f"""
        INSERT INTO {table} ({col_sql})
        SELECT {value_sql}
        WHERE NOT EXISTS (
            SELECT 1
            FROM {table}
            WHERE {identity_sql}
        )
        """,
        tuple(row) + identity_values,
    )
    return cur.rowcount or 0


def store_governance_snapshot(
    conn,
    cbe: str,
    deposit_key: str,
    fiscal_year: int | str | None,
    filing_json: dict[str, Any] | None,
) -> dict[str, int]:
    """Insert governance rows for one filing. Safe to re-run."""
    rows = extract_governance_snapshot(cbe, deposit_key, fiscal_year, filing_json)
    counts = {
        "administrators": 0,
        "shareholders": 0,
        "participating_interests": 0,
        "affiliations": 0,
    }
    if not any(rows.values()):
        return counts

    cur = conn.cursor()
    try:
        for row in rows["administrators"]:
            counts["administrators"] += _insert_unique(
                cur,
                "administrator",
                _ADMIN_COLUMNS,
                ("enterprise_number", "deposit_key", "name", "role"),
                row,
            )
        for row in rows["shareholders"]:
            counts["shareholders"] += _insert_unique(
                cur,
                "shareholder",
                _SHAREHOLDER_COLUMNS,
                ("enterprise_number", "deposit_key", "name"),
                row,
            )
        for row in rows["participating_interests"]:
            counts["participating_interests"] += _insert_unique(
                cur,
                "participating_interest",
                _PI_COLUMNS,
                ("enterprise_number", "deposit_key", "name"),
                row,
            )
        # `affiliation` may not exist on environments that haven't yet
        # applied the affiliation migration. Probe the catalog once and
        # skip silently rather than aborting the whole snapshot — that
        # would rollback all governance writes for older deployments.
        if rows["affiliations"] and _affiliation_table_exists(cur):
            for row in rows["affiliations"]:
                counts["affiliations"] += _insert_unique(
                    cur,
                    "affiliation",
                    _AFFILIATION_COLUMNS,
                    (
                        "person_name",
                        "enterprise_number",
                        "via_enterprise_number",
                        "affiliation_type",
                    ),
                    row,
                )
        conn.commit()
        return counts
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


_AFFILIATION_TABLE_PRESENT: bool | None = None


def _affiliation_table_exists(cur) -> bool:
    """Return True if the `affiliation` table is present in the current schema.

    Cached at module level rather than on the connection because psycopg2's
    `psycopg2.extensions.connection` is a C-extension type that rejects
    arbitrary attribute assignment. Module-level caching is safe here:
    schema state is process-wide, every connection in the pool sees the
    same `public.affiliation` table.
    """
    global _AFFILIATION_TABLE_PRESENT
    if _AFFILIATION_TABLE_PRESENT is not None:
        return _AFFILIATION_TABLE_PRESENT
    cur.execute(
        "SELECT to_regclass('public.affiliation') IS NOT NULL"
    )
    _AFFILIATION_TABLE_PRESENT = bool(cur.fetchone()[0])
    return _AFFILIATION_TABLE_PRESENT
