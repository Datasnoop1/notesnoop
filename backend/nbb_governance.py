"""Helpers for extracting and storing governance rows from NBB filings."""

from __future__ import annotations

from datetime import date
import json
from typing import Any

from ownership_id import (
    OwnershipParent,
    classify_nbb_owner,
    clean_cbe as clean_ownership_cbe,
    company_parent,
)


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

_OWNERSHIP_EDGE_COLUMNS = (
    "parent_kind",
    "parent_id",
    "parent_name_raw",
    "parent_identifier_scheme",
    "parent_identifier_value",
    "parent_country",
    "child_kind",
    "child_id",
    "pct",
    "edge_kind",
    "source_table",
    "source_pk",
    "source_action_seq",
    "source_filing",
    "source_rank",
    "fiscal_year",
    "valid_from",
    "valid_to",
    "confidence",
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


def _source_pk(*parts: Any) -> str:
    return "|".join(str(part) for part in parts if part is not None)


def _fiscal_year_int(raw: Any) -> int | None:
    if raw in (None, ""):
        return None
    text = str(raw).strip()
    if not text.isdigit() or len(text) != 4:
        return None
    year = int(text)
    return year if 1800 <= year <= 2200 else None


def _valid_from_for_fiscal_year(raw: Any) -> date | None:
    year = _fiscal_year_int(raw)
    return date(year, 1, 1) if year is not None else None


def _pct_decimal(raw: Any) -> float | None:
    value = _as_float(raw)
    if value is None:
        return None
    return round(max(0.0, min(100.0, value)), 2)


def _edge_values(parent: OwnershipParent, edge: dict[str, Any]) -> tuple:
    values = {
        "parent_kind": parent.parent_kind,
        "parent_id": parent.parent_id,
        "parent_name_raw": parent.parent_name_raw,
        "parent_identifier_scheme": parent.parent_identifier_scheme,
        "parent_identifier_value": parent.parent_identifier_value,
        "parent_country": parent.parent_country,
        "child_kind": "company",
        **edge,
    }
    return tuple(values.get(column) for column in _OWNERSHIP_EDGE_COLUMNS)


def _upsert_ownership_edge(cur, parent: OwnershipParent, edge: dict[str, Any]) -> int:
    col_sql = ", ".join(_OWNERSHIP_EDGE_COLUMNS)
    value_sql = ", ".join(["%s"] * len(_OWNERSHIP_EDGE_COLUMNS))
    update_sql = """
        parent_kind = EXCLUDED.parent_kind,
        parent_id = EXCLUDED.parent_id,
        parent_name_raw = EXCLUDED.parent_name_raw,
        parent_identifier_scheme = EXCLUDED.parent_identifier_scheme,
        parent_identifier_value = EXCLUDED.parent_identifier_value,
        parent_country = EXCLUDED.parent_country,
        child_kind = EXCLUDED.child_kind,
        child_id = EXCLUDED.child_id,
        pct = EXCLUDED.pct,
        edge_kind = EXCLUDED.edge_kind,
        source_filing = EXCLUDED.source_filing,
        source_rank = EXCLUDED.source_rank,
        fiscal_year = EXCLUDED.fiscal_year,
        valid_from = EXCLUDED.valid_from,
        valid_to = EXCLUDED.valid_to,
        confidence = EXCLUDED.confidence,
        updated_at = NOW()
    """
    cur.execute(
        f"""
        INSERT INTO ownership_edge ({col_sql})
        VALUES ({value_sql})
        ON CONFLICT (source_table, source_pk, source_action_seq) DO UPDATE
        SET {update_sql}
        WHERE ROW(
            ownership_edge.parent_kind,
            ownership_edge.parent_id,
            ownership_edge.parent_name_raw,
            ownership_edge.parent_identifier_scheme,
            ownership_edge.parent_identifier_value,
            ownership_edge.parent_country,
            ownership_edge.child_kind,
            ownership_edge.child_id,
            ownership_edge.pct,
            ownership_edge.edge_kind,
            ownership_edge.source_filing,
            ownership_edge.source_rank,
            ownership_edge.fiscal_year,
            ownership_edge.valid_from,
            ownership_edge.valid_to,
            ownership_edge.confidence
        ) IS DISTINCT FROM ROW(
            EXCLUDED.parent_kind,
            EXCLUDED.parent_id,
            EXCLUDED.parent_name_raw,
            EXCLUDED.parent_identifier_scheme,
            EXCLUDED.parent_identifier_value,
            EXCLUDED.parent_country,
            EXCLUDED.child_kind,
            EXCLUDED.child_id,
            EXCLUDED.pct,
            EXCLUDED.edge_kind,
            EXCLUDED.source_filing,
            EXCLUDED.source_rank,
            EXCLUDED.fiscal_year,
            EXCLUDED.valid_from,
            EXCLUDED.valid_to,
            EXCLUDED.confidence
        )
        """,
        _edge_values(parent, edge),
    )
    return cur.rowcount or 0


def _ownership_edge_from_shareholder(row: tuple) -> tuple[OwnershipParent, dict[str, Any]] | None:
    data = dict(zip(_SHAREHOLDER_COLUMNS, row))
    child_id = clean_ownership_cbe(data.get("enterprise_number"))
    name = (data.get("name") or "").strip()
    if not child_id or not name:
        return None

    parent = classify_nbb_owner(
        name=name,
        identifier=data.get("identifier"),
        owner_type=data.get("shareholder_type"),
    )
    fiscal_year = _fiscal_year_int(data.get("fiscal_year"))
    return parent, {
        "child_id": child_id,
        "pct": _pct_decimal(data.get("ownership_pct")),
        "edge_kind": "shareholder",
        "source_table": "shareholder",
        "source_pk": _source_pk(child_id, data.get("deposit_key"), name),
        "source_action_seq": 0,
        "source_filing": data.get("deposit_key"),
        "source_rank": 1,
        "fiscal_year": fiscal_year,
        "valid_from": _valid_from_for_fiscal_year(fiscal_year),
        "valid_to": None,
        "confidence": 1.0,
    }


def _ownership_edge_from_pi(row: tuple) -> tuple[OwnershipParent, dict[str, Any]] | None:
    data = dict(zip(_PI_COLUMNS, row))
    parent_id = clean_ownership_cbe(data.get("enterprise_number"))
    child_id = clean_ownership_cbe(data.get("identifier"))
    name = (data.get("name") or "").strip()
    if not parent_id or not child_id or parent_id == child_id:
        return None

    parent = company_parent(parent_id)
    fiscal_year = _fiscal_year_int(data.get("fiscal_year"))
    return parent, {
        "child_id": child_id,
        "pct": _pct_decimal(data.get("ownership_pct")),
        "edge_kind": "participating",
        "source_table": "participating_interest",
        "source_pk": _source_pk(parent_id, data.get("deposit_key"), name),
        "source_action_seq": 0,
        "source_filing": data.get("deposit_key"),
        "source_rank": 2,
        "fiscal_year": fiscal_year,
        "valid_from": _valid_from_for_fiscal_year(fiscal_year),
        "valid_to": None,
        "confidence": 1.0,
    }


def _close_superseded_ownership_edges(
    cur,
    *,
    source_table: str,
    boundary_column: str,
    boundary_id: str,
    fiscal_year: int | None,
) -> int:
    if fiscal_year is None:
        return 0
    valid_to = date(fiscal_year, 1, 1)
    cur.execute(
        f"""
        UPDATE ownership_edge
        SET valid_to = %s,
            updated_at = NOW()
        WHERE source_table = %s
          AND {boundary_column} = %s
          AND fiscal_year IS NOT NULL
          AND fiscal_year < %s
          AND valid_to IS NULL
        """,
        (valid_to, source_table, boundary_id, fiscal_year),
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
        "ownership_edges": 0,
        "ownership_edges_closed": 0,
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
        if _ownership_edge_table_exists(cur):
            shareholder_fy = _fiscal_year_int(fiscal_year)
            child_cbe = clean_ownership_cbe(cbe)
            for row in rows["shareholders"]:
                ownership_row = _ownership_edge_from_shareholder(row)
                if ownership_row is None:
                    continue
                parent, edge = ownership_row
                counts["ownership_edges"] += _upsert_ownership_edge(cur, parent, edge)
            if child_cbe:
                counts["ownership_edges_closed"] += _close_superseded_ownership_edges(
                    cur,
                    source_table="shareholder",
                    boundary_column="child_id",
                    boundary_id=child_cbe,
                    fiscal_year=shareholder_fy,
                )

            parent_cbe = child_cbe
            for row in rows["participating_interests"]:
                ownership_row = _ownership_edge_from_pi(row)
                if ownership_row is None:
                    continue
                parent, edge = ownership_row
                counts["ownership_edges"] += _upsert_ownership_edge(cur, parent, edge)
            if parent_cbe:
                counts["ownership_edges_closed"] += _close_superseded_ownership_edges(
                    cur,
                    source_table="participating_interest",
                    boundary_column="parent_id",
                    boundary_id=parent_cbe,
                    fiscal_year=shareholder_fy,
                )
        conn.commit()
        return counts
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


_AFFILIATION_TABLE_PRESENT: bool | None = None
_OWNERSHIP_EDGE_TABLE_PRESENT: bool | None = None
_GOVERNANCE_LOAD_LOG_TABLE_PRESENT: bool | None = None


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


def _ownership_edge_table_exists(cur) -> bool:
    """Return True if the Ownership graph migration has landed."""
    global _OWNERSHIP_EDGE_TABLE_PRESENT
    if _OWNERSHIP_EDGE_TABLE_PRESENT is not None:
        return _OWNERSHIP_EDGE_TABLE_PRESENT
    cur.execute(
        "SELECT to_regclass('public.ownership_edge') IS NOT NULL"
    )
    _OWNERSHIP_EDGE_TABLE_PRESENT = bool(cur.fetchone()[0])
    return _OWNERSHIP_EDGE_TABLE_PRESENT


def _governance_load_log_table_exists(cur) -> bool:
    """Return True if the governance retry log migration has landed."""
    global _GOVERNANCE_LOAD_LOG_TABLE_PRESENT
    if _GOVERNANCE_LOAD_LOG_TABLE_PRESENT is not None:
        return _GOVERNANCE_LOAD_LOG_TABLE_PRESENT
    cur.execute(
        "SELECT to_regclass('public.governance_load_log') IS NOT NULL"
    )
    _GOVERNANCE_LOAD_LOG_TABLE_PRESENT = bool(cur.fetchone()[0])
    return _GOVERNANCE_LOAD_LOG_TABLE_PRESENT


def record_governance_load_success(
    conn,
    cbe: str,
    deposit_key: str,
    counts: dict[str, int],
) -> None:
    """Mark one filing's governance extraction durable and successful."""
    cur = conn.cursor()
    try:
        if not _governance_load_log_table_exists(cur):
            return
        cur.execute(
            """
            INSERT INTO governance_load_log (
                enterprise_number, deposit_key, status, attempts,
                last_error, counts_json, last_attempt_at, next_retry_at
            )
            VALUES (%s, %s, 'ok', 0, NULL, %s::jsonb, NOW(), NULL)
            ON CONFLICT (enterprise_number, deposit_key) DO UPDATE
            SET status = 'ok',
                last_error = NULL,
                counts_json = EXCLUDED.counts_json,
                last_attempt_at = NOW(),
                next_retry_at = NULL,
                updated_at = NOW()
            """,
            (cbe, deposit_key, json.dumps(counts, sort_keys=True)),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


def record_governance_load_failure(
    conn,
    cbe: str,
    deposit_key: str,
    error: Exception | str,
) -> None:
    """Persist one failed governance extraction for retry."""
    cur = conn.cursor()
    try:
        if not _governance_load_log_table_exists(cur):
            return
        message = str(error)[:4000]
        cur.execute(
            """
            INSERT INTO governance_load_log (
                enterprise_number, deposit_key, status, attempts,
                last_error, counts_json, last_attempt_at, next_retry_at
            )
            VALUES (%s, %s, 'error', 1, %s, NULL, NOW(), NOW() + INTERVAL '1 hour')
            ON CONFLICT (enterprise_number, deposit_key) DO UPDATE
            SET status = 'error',
                attempts = governance_load_log.attempts + 1,
                last_error = EXCLUDED.last_error,
                counts_json = NULL,
                last_attempt_at = NOW(),
                next_retry_at = NOW() + INTERVAL '1 hour',
                updated_at = NOW()
            """,
            (cbe, deposit_key, message),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
