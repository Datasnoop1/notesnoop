from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
NBB_GOVERNANCE = ROOT / "backend" / "nbb_governance.py"
STRUCTURE_ROUTER = ROOT / "backend" / "routers" / "companies" / "structure.py"


def test_nbb_governance_writer_stamps_loader_provenance_when_columns_exist():
    source = NBB_GOVERNANCE.read_text(encoding="utf-8")

    assert "_PROVENANCE_INSERT_COLUMNS" in source
    assert "_table_has_provenance_columns" in source
    assert "valid_from_provenance=\"nbb_loader_direct\"" in source
    assert "valid_to_provenance=\"nbb_loader_direct\"" in source


def test_staatsblad_projection_stamps_consumer_provenance_when_columns_exist():
    source = STRUCTURE_ROUTER.read_text(encoding="utf-8")

    assert "_administrator_provenance_columns_present" in source
    assert "valid_from_provenance" in source
    assert "valid_to_provenance" in source
    assert "staatsblad_consumer_direct" in source
