from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np

from app.models import AttackSpec, EventSpec, Scenario, Tick


def generate_ticks(scenario: Scenario, seed: int | None = None) -> list[Tick]:
    rng = np.random.default_rng(scenario.seed if seed is None else seed)
    event_magnitudes = _draw_event_magnitudes(scenario, rng)
    goal_magnitudes = _draw_goal_magnitudes(scenario, rng)
    attack_magnitudes = _draw_attack_magnitudes(scenario, rng)

    ticks: list[Tick] = []
    current = scenario.sim_start
    while current < scenario.sim_end:
        active_events = [
            event.id for event in scenario.events if _is_active(current, event.start, event.end)
        ]
        truth = [
            f"attack:{attack.id}"
            for attack in scenario.attacks
            if _is_active(current, attack.start, attack.end)
        ]
        kpis = _baseline_values(scenario, rng)
        _apply_events(kpis, scenario, current, event_magnitudes, goal_magnitudes)
        _apply_load_reactions(kpis, scenario)
        _apply_attacks(kpis, scenario, current, attack_magnitudes)
        ticks.append(
            Tick(
                ts=current,
                kpis={key: round(max(value, 0.0), 6) for key, value in kpis.items()},
                active_events=active_events,
                truth=truth,
            )
        )
        current += timedelta(seconds=scenario.tick_seconds)
    return ticks


def _baseline_values(scenario: Scenario, rng: np.random.Generator) -> dict[str, float]:
    values: dict[str, float] = {}
    for kpi in scenario.kpis:
        noise = float(np.clip(rng.normal(0.0, 0.012), -0.03, 0.03))
        values[kpi.id] = kpi.baseline * (1.0 + noise)
    return values


def _draw_event_magnitudes(
    scenario: Scenario, rng: np.random.Generator
) -> dict[tuple[str, str], float]:
    magnitudes: dict[tuple[str, str], float] = {}
    for event in scenario.events:
        for impact in event.expected_impacts:
            magnitudes[(event.id, impact.kpi)] = float(rng.uniform(impact.low, impact.high))
    return magnitudes


def _draw_goal_magnitudes(
    scenario: Scenario, rng: np.random.Generator
) -> dict[tuple[str, datetime], tuple[float, float]]:
    magnitudes: dict[tuple[str, datetime], tuple[float, float]] = {}
    for event in scenario.events:
        if event.kind != "match":
            continue
        for goal in event.goals:
            extra_multiplier = float(rng.uniform(1.5, 2.5))
            decay_seconds = float(rng.uniform(120.0, 240.0))
            magnitudes[(event.id, goal)] = (extra_multiplier, decay_seconds)
    return magnitudes


def _draw_attack_magnitudes(
    scenario: Scenario, rng: np.random.Generator
) -> dict[str, float]:
    return {
        attack.id: float(rng.uniform(attack.multiplier.low, attack.multiplier.high))
        for attack in scenario.attacks
    }


def _apply_events(
    kpis: dict[str, float],
    scenario: Scenario,
    ts: datetime,
    event_magnitudes: dict[tuple[str, str], float],
    goal_magnitudes: dict[tuple[str, datetime], tuple[float, float]],
) -> None:
    for event in scenario.events:
        for impact in event.expected_impacts:
            shape = _event_shape(event, ts)
            if shape <= 0.0:
                continue
            magnitude = event_magnitudes[(event.id, impact.kpi)]
            multiplier = 1.0 + (magnitude - 1.0) * shape
            kpis[impact.kpi] *= multiplier
        _apply_goal_spikes(kpis, event, ts, goal_magnitudes, scenario.baselines)


def _event_shape(event: EventSpec, ts: datetime) -> float:
    if event.kind == "match":
        return _match_shape(event, ts)
    return _campaign_shape(event, ts)


def _match_shape(event: EventSpec, ts: datetime) -> float:
    if event.pre_ramp_start is None or event.kickoff is None or event.full_time is None:
        return 0.0
    if ts < event.pre_ramp_start or ts > event.full_time:
        return 0.0
    if ts < event.kickoff:
        total = (event.kickoff - event.pre_ramp_start).total_seconds()
        elapsed = (ts - event.pre_ramp_start).total_seconds()
        return _smoothstep(elapsed / total)
    return 1.0


def _campaign_shape(event: EventSpec, ts: datetime) -> float:
    tail_seconds = 150.0
    if ts < event.start or ts > event.end + timedelta(seconds=tail_seconds):
        return 0.0
    if ts <= event.end:
        rise_seconds = 10.0
        elapsed = (ts - event.start).total_seconds()
        return min(1.0, max(0.0, elapsed / rise_seconds))
    since_end = (ts - event.end).total_seconds()
    return float(np.exp(-since_end / tail_seconds))


def _apply_goal_spikes(
    kpis: dict[str, float],
    event: EventSpec,
    ts: datetime,
    goal_magnitudes: dict[tuple[str, datetime], tuple[float, float]],
    baselines: dict[str, float],
) -> None:
    if event.kind != "match":
        return
    for goal in event.goals:
        if ts < goal:
            continue
        elapsed = (ts - goal).total_seconds()
        extra_multiplier, decay_seconds = goal_magnitudes[(event.id, goal)]
        if elapsed > decay_seconds * 2:
            continue
        extra = extra_multiplier * float(np.exp(-elapsed / decay_seconds))
        if "edge_rps" in kpis and "edge_rps" in baselines:
            kpis["edge_rps"] += baselines["edge_rps"] * extra


def _apply_load_reactions(kpis: dict[str, float], scenario: Scenario) -> None:
    baselines = scenario.baselines
    volume_kpis = [
        key
        for key in ("streaming_concurrents", "edge_rps", "checkout_rps", "auth_login_rps")
        if key in kpis and key in baselines
    ]
    if not volume_kpis:
        return
    load_ratio = max(kpis[key] / baselines[key] for key in volume_kpis)
    excess = max(load_ratio - 1.0, 0.0)
    if "p99_latency_ms" in kpis:
        kpis["p99_latency_ms"] *= 1.0 + min(0.14, 0.0045 * excess)
    if "error_rate_5xx" in kpis:
        kpis["error_rate_5xx"] += min(0.001, 0.00002 * excess)


def _apply_attacks(
    kpis: dict[str, float],
    scenario: Scenario,
    ts: datetime,
    attack_magnitudes: dict[str, float],
) -> None:
    for attack in scenario.attacks:
        if not _is_active(ts, attack.start, attack.end):
            continue
        kpis[attack.target_kpi] *= attack_magnitudes[attack.id]
        for impact in attack.additive_impacts:
            kpis[impact.kpi] += impact.value


def _is_active(ts: datetime, start: datetime, end: datetime) -> bool:
    return start <= ts <= end


def _smoothstep(value: float) -> float:
    clipped = min(1.0, max(0.0, value))
    return clipped * clipped * (3.0 - 2.0 * clipped)
