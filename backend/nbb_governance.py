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
        return {"administrators": [], "shareholders": [], "participating_interests": []}

    fiscal_year_text = str(fiscal_year) if fiscal_year not in (None, "") else None
    admin_rows: list[tuple] = []
    shareholder_rows: list[tuple] = []
    pi_rows: list[tuple] = []

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
                _pick(entity, "Identifier", "identifier"),
                _pick(dates, "StartDate", "startDate"),
                _pick(dates, "EndDate", "endDate"),
                None,
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
    counts = {"administrators": 0, "shareholders": 0, "participating_interests": 0}
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
        conn.commit()
        return counts
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
