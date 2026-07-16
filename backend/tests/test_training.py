from __future__ import annotations


def test_validation_coverage_in_expected_range(trained_meta) -> None:
    for kpi_id, coverage in trained_meta["validation_coverage"].items():
        assert 0.65 <= coverage <= 0.98, f"{kpi_id} coverage {coverage}"
