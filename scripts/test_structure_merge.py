"""Regression tests for company administrator merge logic.

The company profile should treat the latest NBB filing as the baseline
board snapshot, then only let later Staatsblad admin events update it.
Older Staatsblad history must not wipe out directors that still appear
in the newer filing.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "backend"
    / "routers"
    / "companies"
    / "structure_merge.py"
)

spec = importlib.util.spec_from_file_location("structure_merge", MODULE_PATH)
assert spec and spec.loader, f"Could not load merge helper from {MODULE_PATH}"
structure_merge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(structure_merge)

merge_admins_with_staatsblad = structure_merge.merge_admins_with_staatsblad


ROLE_LABELS = {"fct:m13": "Administrator"}


def _nbb_admin(name: str) -> dict:
    return {
        "name": name,
        "role": "fct:m13",
        "person_type": "natural",
        "identifier": None,
        "mandate_start": "2020-01-01",
        "mandate_end": None,
        "representative_name": None,
        "fiscal_year": "2023",
        "deposit_date": "2024-01-20",
        "deposit_key": "2024-00001234",
    }


def test_old_staatsblad_history_does_not_clobber_newer_nbb_snapshot():
    nbb_rows = [_nbb_admin("Alice Example"), _nbb_admin("Bob Example")]
    events = [
        {
            "id": 1,
            "event_type": "admin_event",
            "sub_type": "resignation",
            "pub_date": "2022-04-10",
            "event_date": "2022-04-01",
            "person_name": "Bob Example",
            "person_role": "Administrator",
            "entity_name": None,
            "pub_reference": "2022-0001",
            "summary": "Older resignation that predates the NBB snapshot",
        },
        {
            "id": 2,
            "event_type": "admin_event",
            "sub_type": "appointment",
            "pub_date": "2024-02-15",
            "event_date": "2024-02-01",
            "person_name": "Cara Example",
            "person_role": "Administrator",
            "entity_name": None,
            "pub_reference": "2024-0002",
            "summary": "Later appointment that should extend the NBB board",
        },
    ]

    current, timeline = merge_admins_with_staatsblad(
        nbb_rows,
        events,
        role_labels=ROLE_LABELS,
    )

    assert [row["name"] for row in current] == [
        "Alice Example",
        "Bob Example",
        "Cara Example",
    ]
    assert timeline[0]["person_name"] == "Cara Example"
    assert timeline[1]["person_name"] == "Bob Example"
    print("Test 1 passed: pre-baseline Staatsblad history no longer removes NBB admins")


def test_newer_staatsblad_resignation_still_updates_board():
    nbb_rows = [_nbb_admin("Alice Example"), _nbb_admin("Bob Example")]
    events = [
        {
            "id": 3,
            "event_type": "admin_event",
            "sub_type": "resignation",
            "pub_date": "2024-03-10",
            "event_date": "2024-03-01",
            "person_name": "Bob Example",
            "person_role": "Administrator",
            "entity_name": None,
            "pub_reference": "2024-0003",
            "summary": "Later resignation that should override the 2023 NBB snapshot",
        }
    ]

    current, _timeline = merge_admins_with_staatsblad(
        nbb_rows,
        events,
        role_labels=ROLE_LABELS,
    )

    active_names = [row["name"] for row in current if not row.get("mandate_end")]
    ended = [row for row in current if row.get("name") == "Bob Example"]

    assert active_names == ["Alice Example"]
    assert ended and ended[0]["mandate_end"] == "2024-03-01"
    print("Test 2 passed: post-baseline Staatsblad resignations still update the board")


if __name__ == "__main__":
    test_old_staatsblad_history_does_not_clobber_newer_nbb_snapshot()
    test_newer_staatsblad_resignation_still_updates_board()
    print()
    print("All tests passed.")
