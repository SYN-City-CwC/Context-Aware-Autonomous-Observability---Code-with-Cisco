from __future__ import annotations

from app.generator import generate_ticks
from app.scenario import DEFAULT_SCENARIO_PATH, load_scenario
from app.timeline import build_timeline


def test_same_seed_produces_identical_ticks_and_decisions() -> None:
    scenario = load_scenario(DEFAULT_SCENARIO_PATH)

    first = build_timeline(scenario)
    second = build_timeline(scenario)

    assert [tick.kpis for tick in first.ticks] == [tick.kpis for tick in second.ticks]
    assert [decision.model_dump(mode="json") for decision in first.decisions] == [
        decision.model_dump(mode="json") for decision in second.decisions
    ]


def test_different_seed_changes_kpi_values() -> None:
    scenario = load_scenario(DEFAULT_SCENARIO_PATH)

    default_ticks = generate_ticks(scenario)
    secret_seed_ticks = generate_ticks(scenario, seed=43)

    assert [tick.kpis for tick in default_ticks] != [
        tick.kpis for tick in secret_seed_ticks
    ]
