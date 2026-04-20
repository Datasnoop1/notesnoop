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
                "Entity": {"Name": "BoardCo BV", "Identifier": "0123456789"},
                "Mandates": [
                    {
                        "FunctionMandate": "fct:m12",
                        "MandateDates": {"StartDate": "2023-06-01", "EndDate": None},
                    }
                ],
            }
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

    assert len(admins) == 2
    assert len(shareholders) == 2
    assert len(pis) == 1

    natural_admin = next(row for row in admins if row[3] == "natural")
    legal_admin = next(row for row in admins if row[3] == "legal")
    entity_shareholder = next(row for row in shareholders if row[3] == "entity")
    individual_shareholder = next(row for row in shareholders if row[3] == "individual")
    subsidiary = pis[0]

    assert natural_admin[1] == "2025-00272929"
    assert natural_admin[2] == "2024"
    assert natural_admin[4] == "Alice Peeters"
    assert natural_admin[5] == "fct:m13"

    assert legal_admin[4] == "BoardCo BV"
    assert legal_admin[6] == "0123456789"

    assert entity_shareholder[4] == "Holding SA"
    assert entity_shareholder[8] == 60.0
    assert individual_shareholder[4] == "Bob Janssens"

    assert subsidiary[3] == "Subsidiary NV"
    assert subsidiary[7] == 25.0

    print("Governance extraction regression checks passed.")


if __name__ == "__main__":
    main()
