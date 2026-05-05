from pathlib import Path
import importlib.util


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "backfill_affiliation.py"


def _module():
    spec = importlib.util.spec_from_file_location("backfill_affiliation_stage_d_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_affiliation_backfill_passes_non_null_deposit_date_to_governance_writer():
    source = SCRIPT.read_text(encoding="utf-8")

    assert "COALESCE(" in source
    assert "NULLIF(btrim(fs.deposit_date), '')" in source
    assert "a.source_deposit_date::text" in source
    assert "AS deposit_date" in source
    assert "pg_input_is_valid(" in source
    assert "BETWEEN DATE '1830-01-01' AND CURRENT_DATE" in source
    assert "LEFT JOIN financial_summary fs" in source
    assert "deposit_date = normalise_deposit_date(deposit_date)" in source
    assert "if not deposit_date:" in source
    assert "failed to record missing-date backfill attempt" not in source
    assert "deposit_date=deposit_date" in source


def test_affiliation_backfill_deposit_date_normalizer_rejects_bad_values():
    module = _module()

    assert module.normalise_deposit_date("2024-05-04") == "2024-05-04"
    assert module.normalise_deposit_date(" 2024-05-04 ") == "2024-05-04"
    assert module.normalise_deposit_date(None) is None
    assert module.normalise_deposit_date("") is None
    assert module.normalise_deposit_date("2026-02-30") is None
    assert module.normalise_deposit_date("05/04/2026") is None
    assert module.normalise_deposit_date("1829-12-31") is None
    assert module.normalise_deposit_date("2099-01-01") is None
