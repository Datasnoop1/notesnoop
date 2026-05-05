from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STRUCTURE_ROUTER = ROOT / "backend" / "routers" / "companies" / "structure.py"


def test_staatsblad_admin_projection_skips_undated_inserts():
    source = STRUCTURE_ROUTER.read_text(encoding="utf-8")

    assert 'ev.get("event_date") or ev.get("pub_date")' in source
    assert "if not pub_date:" in source
    assert "Skipping Staatsblad admin insert" in source
    assert "Skipping Staatsblad admin end update" in source
    assert "continue" in source
    assert "fallback_enterprise_start" not in source
