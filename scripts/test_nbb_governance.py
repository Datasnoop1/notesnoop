"""Small regression checks for NBB governance extraction."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from nbb_governance import extract_governance_snapshot


MOCK_FILING = {
    "Administrators": {
        "NaturalPersons": [
            {
                "Person": {"FirstName": "Alice", "LastName": "Peeters"},
                "Mandates": [
                    {
                        "FunctionMandate": "fct:m13",
                        "MandateDates": {"StartDate": "2024-01-01", "EndDate": None},
                    }
                ],
            }
        ],
        "LegalPersons": [
            {
                "Entity": {"Name": "BoardCo BV", "Identifier": "0123.456.789"},
                "Mandates": [
                    {
                        "FunctionMandate": "fct:m12",
                        "MandateDates": {"StartDate": "2023-06-01", "EndDate": None},
                    }
                ],
                "Representatives": [
                    {"FirstName": "Charlie", "LastName": "Vermeulen"},
                    {"FirstName": "Diana", "LastName": "De Smet"},
                ],
            },
            {
                # Legal-person admin with no Identifier — should NOT yield
                # affiliation rows because we cannot resolve Company 2.
                "Entity": {"Name": "OrphanCo NV"},
                "Mandates": [
                    {"FunctionMandate": "fct:m13", "MandateDates": {}},
                ],
                "Representatives": [
                    {"FirstName": "Eve", "LastName": "Anonymous"},
                ],
            },
        ],
    },
    "ParticipatingInterests": [
        {
            "Entity": {"Name": "Subsidiary NV", "Identifier": "1111222233"},
            "ParticipatingInterestHeld": [{"PercentageDirectlyHeld": "0.25"}],
        }
    ],
    "Shareholders": {
        "EntityShareHolders": [
            {
                "Entity": {"Name": "Holding SA", "Identifier": "9999888877"},
                "SharesHeld": [{"PercentageDirectlyHeld": "0.60"}],
            }
        ],
        "IndividualShareHolders": [
            {
                "Person": {"FirstName": "Bob", "LastName": "Janssens"},
            }
        ],
    },
}


def main() -> None:
    rows = extract_governance_snapshot("0782324497", "2025-00272929", 2024, MOCK_FILING)

    admins = rows["administrators"]
    shareholders = rows["shareholders"]
    pis = rows["participating_interests"]
    affiliations = rows["affiliations"]

    assert len(admins) == 3
    assert len(shareholders) == 2
    assert len(pis) == 1
    # Two reps for BoardCo BV, zero for OrphanCo NV (no identifier).
    assert len(affiliations) == 2

    natural_admin = next(row for row in admins if row[3] == "natural")
    legal_admin = next(row for row in admins if row[3] == "legal" and row[4] == "BoardCo BV")
    orphan_admin = next(row for row in admins if row[3] == "legal" and row[4] == "OrphanCo NV")
    entity_shareholder = next(row for row in shareholders if row[3] == "entity")
    individual_shareholder = next(row for row in shareholders if row[3] == "individual")
    subsidiary = pis[0]

    assert natural_admin[1] == "2025-00272929"
    assert natural_admin[2] == "2024"
    assert natural_admin[4] == "Alice Peeters"
    assert natural_admin[5] == "fct:m13"

    assert legal_admin[4] == "BoardCo BV"
    # `representative_name` legacy column carries the first rep for
    # backward compatibility.
    assert legal_admin[9] == "Charlie Vermeulen"
    assert orphan_admin[9] == "Eve Anonymous"

    assert entity_shareholder[4] == "Holding SA"
    assert entity_shareholder[8] == 60.0
    assert individual_shareholder[4] == "Bob Janssens"

    assert subsidiary[3] == "Subsidiary NV"
    assert subsidiary[7] == 25.0

    # Affiliation rows: column order is (person_name, enterprise_number,
    # via_enterprise_number, via_deposit_key, fiscal_year,
    # affiliation_type, person_identifier).
    charlie = next(row for row in affiliations if row[0] == "Charlie Vermeulen")
    diana = next(row for row in affiliations if row[0] == "Diana De Smet")
    # Identifier with dots stripped to canonical 10-digit form.
    assert charlie[1] == "0123456789"
    # via_enterprise_number is the company whose filing we parsed.
    assert charlie[2] == "0782324497"
    assert charlie[3] == "2025-00272929"
    assert charlie[4] == "2024"
    assert charlie[5] == "represents_admin"
    assert diana[1] == "0123456789"
    assert diana[5] == "represents_admin"

    # OrphanCo NV had a rep but no Identifier → affiliation row cannot
    # be linked, so it must NOT appear.
    assert not any(row[0] == "Eve Anonymous" for row in affiliations)

    print("Governance extraction regression checks passed.")


if __name__ == "__main__":
    main()
