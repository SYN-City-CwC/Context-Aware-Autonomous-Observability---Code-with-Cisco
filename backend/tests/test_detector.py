from __future__ import annotations

from datetime import UTC, datetime

from app.scenario import DEFAULT_SCENARIO_PATH, load_scenario
from app.timeline import build_timeline


WINDOW_START = datetime(2026, 7, 16, 21, 15, tzinfo=UTC)
WINDOW_END = datetime(2026, 7, 16, 21, 27, tzinfo=UTC)
QUIET_END = datetime(2026, 7, 16, 19, 15, tzinfo=UTC)


def test_merch_drop_is_suppressed_and_auth_spike_alerts() -> None:
    timeline = build_timeline(load_scenario(DEFAULT_SCENARIO_PATH))

    checkout_suppressions = [
        decision
        for decision in timeline.decisions
        if decision.verdict == "SUPPRESS"
        and decision.evidence.kpi == "checkout_rps"
        and WINDOW_START <= decision.ts <= WINDOW_END
    ]
    auth_alerts = [
        decision
        for decision in timeline.decisions
        if decision.verdict == "ALERT"
        and decision.evidence.kpi == "auth_login_rps"
        and WINDOW_START <= decision.ts <= WINDOW_END
    ]

    assert any("M-217" in decision.reason for decision in checkout_suppressions)
    assert auth_alerts


def test_no_checkout_alerts_and_no_pre_event_decisions() -> None:
    timeline = build_timeline(load_scenario(DEFAULT_SCENARIO_PATH))

    assert [
        decision
        for decision in timeline.decisions
        if decision.verdict == "ALERT" and decision.evidence.kpi == "checkout_rps"
    ] == []
    assert [decision for decision in timeline.decisions if decision.ts < QUIET_END] == []


def test_detector_output_never_mentions_truth_or_attack_id() -> None:
    timeline = build_timeline(load_scenario(DEFAULT_SCENARIO_PATH))

    for decision in timeline.decisions:
        serialized = f"{decision.reason} {decision.evidence.model_dump(mode='json')}"
        assert "CS-01" not in serialized
        assert "attack:" not in serialized
        assert "truth" not in serialized
