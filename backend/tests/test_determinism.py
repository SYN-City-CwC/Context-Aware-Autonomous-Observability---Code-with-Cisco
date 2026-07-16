from __future__ import annotations

from app.envelope import run_envelope_detector
from app.generator import generate_ticks
from app.scenario import DEFAULT_SCENARIO_PATH, load_scenario
from app.train import train_models


def test_same_models_produce_identical_envelope_arrays(envelope_timeline, scenario) -> None:
    second_ticks, _ = run_envelope_detector(scenario, generate_ticks(scenario))

    assert [tick.envelope for tick in envelope_timeline.ticks] == [
        tick.envelope for tick in second_ticks
    ]


def test_full_train_and_predict_runs_are_deterministic(tmp_path) -> None:
    scenario = load_scenario(DEFAULT_SCENARIO_PATH)
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"

    train_models(scenario, model_dir=first_dir, n_estimators=20, verbose=False)
    train_models(scenario, model_dir=second_dir, n_estimators=20, verbose=False)
    first_ticks, first_decisions = run_envelope_detector(
        scenario, generate_ticks(scenario), model_dir=first_dir
    )
    second_ticks, second_decisions = run_envelope_detector(
        scenario, generate_ticks(scenario), model_dir=second_dir
    )

    assert [tick.envelope for tick in first_ticks] == [tick.envelope for tick in second_ticks]
    assert [decision.model_dump(mode="json") for decision in first_decisions] == [
        decision.model_dump(mode="json") for decision in second_decisions
    ]


def test_different_seed_changes_kpi_values() -> None:
    scenario = load_scenario(DEFAULT_SCENARIO_PATH)

    default_ticks = generate_ticks(scenario)
    secret_seed_ticks = generate_ticks(scenario, seed=43)

    assert [tick.kpis for tick in default_ticks] != [
        tick.kpis for tick in secret_seed_ticks
    ]
