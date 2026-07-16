from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from statistics import median
from typing import Sequence

from app.models import (
    Decision,
    DeclaredRange,
    DetectorTick,
    EventSpec,
    Evidence,
    ExpectedImpact,
    Scenario,
)


WINDOW_SECONDS = 30 * 60
DEFAULT_THRESHOLD = 1.8
SENSITIVE_THRESHOLD = 1.6
SENSITIVE_KPIS = {"error_rate_5xx", "p99_latency_ms"}


@dataclass
class EpisodeState:
    active: bool = False
    clear_ticks: int = 0


@dataclass(frozen=True)
class ImpactCandidate:
    event: EventSpec
    impact: ExpectedImpact
    fit: float


def run_detector(scenario: Scenario, ticks: Sequence[DetectorTick]) -> list[Decision]:
    baselines = scenario.baselines
    window_ticks = max(1, WINDOW_SECONDS // scenario.tick_seconds)
    history: dict[str, deque[float]] = {
        kpi_id: deque(maxlen=window_ticks) for kpi_id in baselines
    }
    episodes = {kpi_id: EpisodeState() for kpi_id in baselines}
    event_by_id = {event.id: event for event in scenario.events}
    decisions: list[Decision] = []

    for tick in ticks:
        for kpi_id in baselines:
            observed = tick.kpis[kpi_id]
            baseline = _rolling_baseline(history[kpi_id], baselines[kpi_id], window_ticks)
            ratio = observed / baseline if baseline > 0 else 0.0
            threshold = SENSITIVE_THRESHOLD if kpi_id in SENSITIVE_KPIS else DEFAULT_THRESHOLD
            state = episodes[kpi_id]
            if not state.active and ratio > threshold:
                decision = _open_episode_decision(
                    tick=tick,
                    kpi_id=kpi_id,
                    observed=observed,
                    baseline=baseline,
                    ratio=ratio,
                    active_events=[event_by_id[event_id] for event_id in tick.active_events],
                )
                decisions.append(decision)
                state.active = True
                state.clear_ticks = 0
            elif state.active:
                if ratio <= threshold:
                    state.clear_ticks += 1
                    if state.clear_ticks >= 3:
                        state.active = False
                        state.clear_ticks = 0
                else:
                    state.clear_ticks = 0
            history[kpi_id].append(observed)
    return decisions


def _rolling_baseline(history: deque[float], fallback: float, window_ticks: int) -> float:
    if len(history) < window_ticks:
        return fallback
    return float(median(history))


def _open_episode_decision(
    tick: DetectorTick,
    kpi_id: str,
    observed: float,
    baseline: float,
    ratio: float,
    active_events: list[EventSpec],
) -> Decision:
    candidate = _best_expected_candidate(kpi_id, ratio, active_events)
    declared_range = (
        DeclaredRange(
            event_id=candidate.event.id,
            low=candidate.impact.low,
            high=candidate.impact.high,
        )
        if candidate is not None
        else _first_declared_range(kpi_id, active_events)
    )
    evidence = Evidence(
        kpi=kpi_id,
        observed=round(observed, 6),
        baseline=round(baseline, 6),
        ratio=round(ratio, 4),
        active_events=[event.id for event in active_events],
        declared_range=declared_range,
    )
    if candidate is not None:
        confidence = round(0.8 + 0.15 * candidate.fit, 3)
        reason = (
            f"{kpi_id} {ratio:.1f}x baseline; {candidate.event.kind} "
            f"{candidate.event.id} active (expects {candidate.impact.low:.1f}-"
            f"{candidate.impact.high:.1f}x); within expected envelope"
        )
        return Decision(
            ts=tick.ts,
            verdict="SUPPRESS",
            decision_class="expected-event-traffic",
            reason=reason,
            confidence=confidence,
            evidence=evidence,
        )

    # Stage 0 confidence is a simple heuristic; Stage 1 replaces it with model output.
    confidence = round(min(0.9, 0.6 + 0.1 * (ratio / 2.0)), 3)
    reason = (
        f"{kpi_id} {ratio:.1f}x baseline; no declared context explains this deviation"
    )
    return Decision(
        ts=tick.ts,
        verdict="ALERT",
        decision_class="unexplained-deviation",
        reason=reason,
        confidence=confidence,
        evidence=evidence,
    )


def _best_expected_candidate(
    kpi_id: str, ratio: float, active_events: list[EventSpec]
) -> ImpactCandidate | None:
    candidates: list[ImpactCandidate] = []
    for event in active_events:
        for impact in event.expected_impacts:
            if impact.kpi != kpi_id or ratio > impact.high * 1.25:
                continue
            midpoint = (impact.low + impact.high) / 2.0
            half_span = max((impact.high - impact.low) / 2.0, 0.001)
            fit = 1.0 - min(abs(ratio - midpoint) / half_span, 1.0)
            candidates.append(ImpactCandidate(event=event, impact=impact, fit=fit))
    if not candidates:
        return None
    return max(candidates, key=lambda candidate: candidate.fit)


def _first_declared_range(
    kpi_id: str, active_events: list[EventSpec]
) -> DeclaredRange | None:
    for event in active_events:
        for impact in event.expected_impacts:
            if impact.kpi == kpi_id:
                return DeclaredRange(event_id=event.id, low=impact.low, high=impact.high)
    return None
