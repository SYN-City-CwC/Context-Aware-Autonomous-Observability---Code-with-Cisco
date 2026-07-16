from __future__ import annotations

from datetime import UTC, datetime


WINDOW_START = datetime(2026, 7, 16, 21, 15, tzinfo=UTC)
WINDOW_END = datetime(2026, 7, 16, 21, 27, tzinfo=UTC)
LOGIN_ALERT_END = datetime(2026, 7, 16, 21, 18, tzinfo=UTC)
QUIET_END = datetime(2026, 7, 16, 19, 10, tzinfo=UTC)


def test_envelope_merch_drop_suppresses_and_login_alerts(envelope_timeline) -> None:
    checkout_suppressions = [
        decision
        for decision in envelope_timeline.decisions
        if decision.verdict == "SUPPRESS"
        and decision.evidence.kpi == "checkout_rps"
        and WINDOW_START <= decision.ts <= WINDOW_END
    ]
    auth_alerts = [
        decision
        for decision in envelope_timeline.decisions
        if decision.verdict == "ALERT"
        and decision.evidence.kpi == "auth_login_rps"
        and WINDOW_START <= decision.ts <= LOGIN_ALERT_END
    ]
    checkout_alerts = [
        decision
        for decision in envelope_timeline.decisions
        if decision.verdict == "ALERT"
        and decision.evidence.kpi == "checkout_rps"
        and WINDOW_START <= decision.ts <= WINDOW_END
    ]

    assert any("M-217" in decision.reason for decision in checkout_suppressions)
    assert auth_alerts
    assert checkout_alerts == []


def test_envelope_is_quiet_before_context_starts(envelope_timeline) -> None:
    assert [decision for decision in envelope_timeline.decisions if decision.ts < QUIET_END] == []


def test_rules_degraded_mode_keeps_stage0_outcomes(rules_timeline) -> None:
    checkout_suppressions = [
        decision
        for decision in rules_timeline.decisions
        if decision.verdict == "SUPPRESS"
        and decision.evidence.kpi == "checkout_rps"
        and WINDOW_START <= decision.ts <= WINDOW_END
    ]
    auth_alerts = [
        decision
        for decision in rules_timeline.decisions
        if decision.verdict == "ALERT"
        and decision.evidence.kpi == "auth_login_rps"
        and WINDOW_START <= decision.ts <= WINDOW_END
    ]
    checkout_alerts = [
        decision
        for decision in rules_timeline.decisions
        if decision.verdict == "ALERT" and decision.evidence.kpi == "checkout_rps"
    ]

    assert any("M-217" in decision.reason for decision in checkout_suppressions)
    assert auth_alerts
    assert checkout_alerts == []


def test_detector_output_never_mentions_truth_or_attack_id(envelope_timeline) -> None:
    for decision in envelope_timeline.decisions:
        serialized = f"{decision.reason} {decision.evidence.model_dump(mode='json')}"
        assert "CS-01" not in serialized
        assert "attack:" not in serialized
        assert "truth" not in serialized
