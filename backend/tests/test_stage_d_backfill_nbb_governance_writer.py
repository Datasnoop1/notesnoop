from pathlib import Path
import importlib.util


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "backfill_nbb_governance.py"


def _module():
    spec = importlib.util.spec_from_file_location("backfill_nbb_governance_stage_d_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_nbb_governance_backfill_passes_non_null_deposit_date_to_writer():
    source = SCRIPT.read_text(encoding="utf-8")

    assert "NULLIF(btrim(deposit_date), '') AS deposit_date" in source
    assert "deposit_date = normalise_deposit_date(deposit_date)" in source
    assert "if not deposit_date:" in source
    assert "skipping governance backfill because no parseable deposit_date is available" in source
    assert "deposit_date=deposit_date" in source
    assert "fiscal_year = normalise_fiscal_year(fiscal_year)" in source
    assert "skipping governance backfill because no parseable fiscal_year is available" in source
    assert "failed_writes += 1" in source
    assert "raise SystemExit(1)" in source


def test_nbb_governance_backfill_deposit_date_normalizer_rejects_bad_values():
    module = _module()

    assert module.normalise_deposit_date("2024-05-04") == "2024-05-04"
    assert module.normalise_deposit_date(" 2024-05-04 ") == "2024-05-04"
    assert module.normalise_deposit_date(None) is None
    assert module.normalise_deposit_date("") is None
    assert module.normalise_deposit_date("2026-02-30") is None
    assert module.normalise_deposit_date("05/04/2026") is None
    assert module.normalise_deposit_date("1829-12-31") is None
    assert module.normalise_deposit_date("2099-01-01") is None


def test_nbb_governance_backfill_fiscal_year_normalizer_rejects_bad_values():
    module = _module()

    assert module.normalise_fiscal_year(2024) == 2024
    assert module.normalise_fiscal_year("2024") == 2024
    assert module.normalise_fiscal_year(None) is None
    assert module.normalise_fiscal_year("") is None
    assert module.normalise_fiscal_year("20x4") is None
    assert module.normalise_fiscal_year("1829") is None
    assert module.normalise_fiscal_year("2099") is None
