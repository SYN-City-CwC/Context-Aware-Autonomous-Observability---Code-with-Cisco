from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np

from app.models import AttackSpec, EventSpec, Scenario, Tick
from app.scenario import all_context_events, resolve_prior_events


def generate_ticks(
    scenario: Scenario, seed: int | None = None, action_start_ts: datetime | None = None
) -> list[Tick]:
    rng = np.random.default_rng(scenario.seed if seed is None else seed)
    events = scenario.events
    event_magnitudes = _draw_event_magnitudes(events, rng)
    goal_magnitudes = _draw_goal_magnitudes(events, rng)
    injected = [*scenario.attacks, *scenario.faults]
    attack_magnitudes = _draw_attack_magnitudes(injected, rng)
    return _generate_window(
        scenario=scenario,
        start=scenario.sim_start,
        end=scenario.sim_end,
        events=events,
        attacks=injected,
        rng=rng,
        event_magnitudes=event_magnitudes,
        goal_magnitudes=goal_magnitudes,
        attack_magnitudes=attack_magnitudes,
        action_start_ts=action_start_ts,
    )


def generate_history(scenario: Scenario, seed: int | None = None) -> list[Tick]:
    if scenario.history is None:
        raise ValueError("scenario history block is required for training")
    rng = np.random.default_rng(scenario.seed if seed is None else seed)
    prior_events = resolve_prior_events(scenario)
    all_events = [*prior_events, *scenario.events]
    event_magnitudes = _draw_event_magnitudes(all_events, rng)
    goal_magnitudes = _draw_goal_magnitudes(all_events, rng)
    injected = [*scenario.attacks, *scenario.faults]
    attack_magnitudes = _draw_attack_magnitudes(injected, rng)

    ticks: list[Tick] = []
    first_offset = -(scenario.history.days - 1)
    for day_offset in range(first_offset, 1):
        start = scenario.sim_start + timedelta(days=day_offset)
        end = scenario.sim_end + timedelta(days=day_offset)
        day_events = [
            event for event in all_events if start.date() <= event.start.date() <= end.date()
        ]
        day_attacks = injected if day_offset == 0 else []
        ticks.extend(
            _generate_window(
                scenario=scenario,
                start=start,
                end=end,
                events=day_events,
                attacks=day_attacks,
                rng=rng,
                event_magnitudes=event_magnitudes,
                goal_magnitudes=goal_magnitudes,
                attack_magnitudes=attack_magnitudes,
                action_start_ts=None,
            )
        )
    return ticks


def context_events_for_training(scenario: Scenario) -> list[EventSpec]:
    return all_context_events(scenario)


def _generate_window(
    scenario: Scenario,
    start: datetime,
    end: datetime,
    events: list[EventSpec],
    attacks: list[AttackSpec],
    rng: np.random.Generator,
    event_magnitudes: dict[tuple[str, str], float],
    goal_magnitudes: dict[tuple[str, datetime], tuple[float, float]],
    attack_magnitudes: dict[str, float],
    action_start_ts: datetime | None = None,
) -> list[Tick]:
    ticks: list[Tick] = []
    current = start
    while current < end:
        active_events = [event.id for event in events if _is_active(current, event.start, event.end)]
        truth = [
            f"attack:{attack.id}"
            for attack in attacks
            if _is_active(current, attack.start, attack.end)
        ]
        kpis = _baseline_values(scenario, current, rng)
        _apply_events(kpis, scenario, events, current, event_magnitudes, goal_magnitudes)
        _apply_load_reactions(kpis, scenario)
        _apply_attacks(kpis, attacks, current, attack_magnitudes, action_start_ts)
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


def _baseline_values(
    scenario: Scenario, ts: datetime, rng: np.random.Generator
) -> dict[str, float]:
    values: dict[str, float] = {}
    for kpi in scenario.kpis:
        noise = float(np.clip(rng.normal(0.0, 0.012), -0.03, 0.03))
        values[kpi.id] = kpi.baseline * _diurnal_multiplier(ts, kpi.diurnal) * (1.0 + noise)
    return values


def _diurnal_multiplier(ts: datetime, amplitude: float) -> float:
    if amplitude <= 0.0:
        return 1.0
    minute = ts.hour * 60 + ts.minute + ts.second / 60.0
    phase = 2.0 * np.pi * (minute - 14 * 60) / (24 * 60)
    return float(1.0 + amplitude * np.sin(phase))


def _draw_event_magnitudes(
    events: list[EventSpec], rng: np.random.Generator
) -> dict[tuple[str, str], float]:
    magnitudes: dict[tuple[str, str], float] = {}
    for event in events:
        for impact in event.expected_impacts:
            magnitudes[(event.id, impact.kpi)] = float(rng.uniform(impact.low, impact.high))
    return magnitudes


def _draw_goal_magnitudes(
    events: list[EventSpec], rng: np.random.Generator
) -> dict[tuple[str, datetime], tuple[float, float]]:
    magnitudes: dict[tuple[str, datetime], tuple[float, float]] = {}
    for event in events:
        if event.kind != "match" or event.goal_impact is None:
            continue
        for goal in event.goals:
            extra_multiplier = float(rng.uniform(event.goal_impact.low, event.goal_impact.high))
            decay_seconds = float(
                rng.uniform(
                    event.goal_impact.decay_seconds_low,
                    event.goal_impact.decay_seconds_high,
                )
            )
            magnitudes[(event.id, goal)] = (extra_multiplier, decay_seconds)
    return magnitudes


def _draw_attack_magnitudes(
    attacks: list[AttackSpec], rng: np.random.Generator
) -> dict[str, float]:
    return {
        attack.id: float(rng.uniform(attack.multiplier.low, attack.multiplier.high))
        for attack in attacks
    }


def _apply_events(
    kpis: dict[str, float],
    scenario: Scenario,
    events: list[EventSpec],
    ts: datetime,
    event_magnitudes: dict[tuple[str, str], float],
    goal_magnitudes: dict[tuple[str, datetime], tuple[float, float]],
) -> None:
    for event in events:
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
    if event.kind != "match" or event.goal_impact is None:
        return
    for goal in event.goals:
        if ts < goal:
            continue
        elapsed = (ts - goal).total_seconds()
        extra_multiplier, decay_seconds = goal_magnitudes[(event.id, goal)]
        if elapsed > decay_seconds * 2:
            continue
        extra = extra_multiplier * float(np.exp(-elapsed / decay_seconds))
        if event.goal_impact.kpi in kpis and event.goal_impact.kpi in baselines:
            kpis[event.goal_impact.kpi] += baselines[event.goal_impact.kpi] * extra


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
    attacks: list[AttackSpec],
    ts: datetime,
    attack_magnitudes: dict[str, float],
    action_start_ts: datetime | None,
) -> None:
    for attack in attacks:
        if not _is_active(ts, attack.start, attack.end):
            continue
        multiplier = attack_magnitudes[attack.id]
        if attack.kind == "credential_stuffing" and action_start_ts is not None and ts >= action_start_ts:
            multiplier = 1.0 + (multiplier - 1.0) * 0.2
        kpis[attack.target_kpi] *= multiplier
        for impact in attack.additive_impacts:
            kpis[impact.kpi] += impact.value


def _is_active(ts: datetime, start: datetime, end: datetime) -> bool:
    return start <= ts <= end


def _smoothstep(value: float) -> float:
    clipped = min(1.0, max(0.0, value))
    return clipped * clipped * (3.0 - 2.0 * clipped)
