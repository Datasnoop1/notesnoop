"""Ownership graph parent identifier helpers."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from search_normalization import normalize_name


_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class OwnershipParent:
    parent_kind: str
    parent_id: str
    parent_name_raw: str | None
    parent_identifier_scheme: str | None
    parent_identifier_value: str | None
    parent_country: str | None = None


def clean_cbe(raw: object) -> str | None:
    if raw in (None, ""):
        return None
    digits = "".join(ch for ch in str(raw) if ch.isdigit())
    return digits if len(digits) == 10 else None


def external_parent_id(scheme: str, value: str) -> str:
    scheme_clean = _clean_identifier_part(scheme)
    value_clean = _clean_identifier_part(value)
    if not scheme_clean or not value_clean:
        raise ValueError("external ownership identifiers need scheme and value")
    return f"{scheme_clean}:{value_clean}"


def unknown_parent_id(name: str, country: str | None = None) -> str:
    name_key = normalize_name(name) or (name or "").strip().lower()
    country_key = (country or "").strip().upper()
    digest = hashlib.sha256(f"{name_key}|{country_key}".encode("utf-8")).hexdigest()
    return f"unknown:{digest[:16]}"


def company_parent(cbe: object, name: str | None = None) -> OwnershipParent:
    cbe_clean = clean_cbe(cbe)
    if not cbe_clean:
        raise ValueError("company ownership parent needs a 10-digit CBE")
    return OwnershipParent(
        parent_kind="company",
        parent_id=cbe_clean,
        parent_name_raw=name,
        parent_identifier_scheme="CBE",
        parent_identifier_value=cbe_clean,
        parent_country="BE",
    )


def person_parent(person_id: object, name: str | None = None) -> OwnershipParent:
    value = str(person_id or "").strip().lower()
    if not _UUID_RE.match(value):
        raise ValueError("person ownership parent needs a UUID")
    return OwnershipParent(
        parent_kind="person",
        parent_id=value,
        parent_name_raw=name,
        parent_identifier_scheme="UUID",
        parent_identifier_value=value,
    )


def external_org_parent(
    scheme: str,
    value: str,
    name: str | None = None,
    country: str | None = None,
) -> OwnershipParent:
    scheme_clean = _clean_identifier_part(scheme)
    value_clean = _clean_identifier_part(value)
    parent_id = external_parent_id(scheme_clean, value_clean)
    return OwnershipParent(
        parent_kind="external_org",
        parent_id=parent_id,
        parent_name_raw=name,
        parent_identifier_scheme=scheme_clean,
        parent_identifier_value=value_clean,
        parent_country=_clean_country(country),
    )


def unknown_parent(name: str, country: str | None = None) -> OwnershipParent:
    if not (name or "").strip():
        raise ValueError("unknown ownership parent needs a name")
    return OwnershipParent(
        parent_kind="unknown",
        parent_id=unknown_parent_id(name, country),
        parent_name_raw=name.strip(),
        parent_identifier_scheme=None,
        parent_identifier_value=None,
        parent_country=_clean_country(country),
    )


def classify_nbb_owner(
    *,
    name: str,
    identifier: object = None,
    owner_type: str | None = None,
    country: str | None = None,
) -> OwnershipParent:
    """Classify an NBB shareholder row into an ownership_edge parent."""
    cbe = clean_cbe(identifier)
    if cbe:
        return company_parent(cbe, name)

    ident = _clean_identifier_part(identifier)
    if ident:
        return external_org_parent("FOREIGN_REG", ident, name, country)

    return unknown_parent(name, country)


def _clean_identifier_part(raw: object) -> str:
    return re.sub(r"\s+", "", str(raw or "").strip().upper())


def _clean_country(raw: str | None) -> str | None:
    country = (raw or "").strip().upper()
    return country[:2] if country else None
