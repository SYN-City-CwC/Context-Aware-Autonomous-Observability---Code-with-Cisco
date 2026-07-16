from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np

from app.models import AttackSpec, EventSpec, MemoryLeakFault, RetryStormFault, Scenario, TelemetrySilenceFault, Tick
from app.scenario import all_context_events, resolve_prior_events


def generate_ticks(
    scenario: Scenario, seed: int | None = None, applied_actions: list[dict] | None = None
) -> list[Tick]:
    rng = np.random.default_rng(scenario.seed if seed is None else seed)
    events = scenario.events
    event_magnitudes = _draw_event_magnitudes(events, rng)
    goal_magnitudes = _draw_goal_magnitudes(events, rng)
    injected = [*scenario.attacks, *[fault for fault in scenario.faults if isinstance(fault, AttackSpec)]]
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
        applied_actions=applied_actions or [],
        faults=scenario.faults,
    )


def generate_history(scenario: Scenario, seed: int | None = None) -> list[Tick]:
    if scenario.history is None:
        raise ValueError("scenario history block is required for training")
    rng = np.random.default_rng(scenario.seed if seed is None else seed)
    prior_events = resolve_prior_events(scenario)
    all_events = [*prior_events, *scenario.events]
    event_magnitudes = _draw_event_magnitudes(all_events, rng)
    goal_magnitudes = _draw_goal_magnitudes(all_events, rng)
    injected = [*scenario.attacks, *[fault for fault in scenario.faults if isinstance(fault, AttackSpec)]]
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
                applied_actions=[],
                faults=[] if day_offset != 0 else scenario.faults,
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
    applied_actions: list[dict] | None = None,
    faults: list[object] | None = None,
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
        truth.extend(f"fault:{fault.id}" for fault in faults or [] if _is_active(current, fault.start, fault.end))
        kpis = _baseline_values(scenario, current, rng)
        _apply_events(kpis, scenario, events, current, event_magnitudes, goal_magnitudes)
        _apply_load_reactions(kpis, scenario)
        _apply_attacks(kpis, attacks, current, attack_magnitudes, applied_actions or [])
        _apply_population_stats(kpis, scenario, attacks, current, attack_magnitudes)
        _apply_faults(kpis, faults or [], current, applied_actions or [])
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
    edge_ratio = kpis.get("edge_rps", baselines.get("edge_rps", 1.0)) / max(baselines.get("edge_rps", 1.0), 1.0)
    for kpi_id, scale in (("syslog_rate", 0.03), ("tcp_half_open", 0.015), ("agent_queue_depth", 0.03)):
        if kpi_id in kpis:
            kpis[kpi_id] *= 1.0 + min(0.15, scale * max(edge_ratio - 1.0, 0.0))
    if "memory_used_mb" in kpis:
        kpis["memory_used_mb"] *= 1.0 + min(0.025, 0.004 * excess)


def _apply_attacks(
    kpis: dict[str, float],
    attacks: list[AttackSpec],
    ts: datetime,
    attack_magnitudes: dict[str, float],
    applied_actions: list[dict],
) -> None:
    for attack in attacks:
        if not _is_active(ts, attack.start, attack.end):
            continue
        multiplier = attack_magnitudes[attack.id]
        if attack.kind == "credential_stuffing":
            removal = max((item["fraction"] for item in applied_actions if item["kind"] == "edge_rate_limit" and ts >= item["ts"]), default=0.0)
            multiplier = 1.0 + (multiplier - 1.0) * (1.0 - removal)
        kpis[attack.target_kpi] *= multiplier
        for impact in attack.additive_impacts:
            kpis[impact.kpi] += impact.value


def _apply_faults(kpis: dict[str, float], faults: list[object], ts: datetime, applied_actions: list[dict]) -> None:
    for fault in faults:
        if not _is_active(ts, fault.start, fault.end):
            continue
        if isinstance(fault, MemoryLeakFault):
            kpis[fault.kpi] += fault.slope_mb_per_min * ((ts - fault.start).total_seconds() / 60.0)
        elif isinstance(fault, TelemetrySilenceFault):
            kpis[fault.kpi] = 0.0
        elif isinstance(fault, RetryStormFault):
            if any(item["kind"] == "config_rollback" and ts >= item["ts"] for item in applied_actions):
                continue
            progress = min(1.0, (ts - fault.start).total_seconds() / 60.0)
            reduction = 0.2 if any(item["kind"] == "circuit_break" and ts >= item["ts"] for item in applied_actions) else 1.0
            kpis["retry_amplification"] = 1.0 + (fault.amplification - 1.0) * progress * reduction
            kpis["p99_latency_ms"] += 2400.0 * progress * reduction
            kpis["error_rate_5xx"] += 0.07 * progress * reduction


def _apply_population_stats(kpis: dict[str, float], scenario: Scenario, attacks: list[AttackSpec], ts: datetime, magnitudes: dict[str, float]) -> None:
    attack = next((item for item in attacks if item.population_profile and _is_active(ts, item.start, item.end)), None)
    if attack is None:
        return
    legit = scenario.baselines["auth_login_rps"]
    bot = legit * (magnitudes[attack.id] - 1.0)
    share = bot / (legit + bot)
    mapping = {"source_entropy": "login_source_entropy", "flow_correlation": "login_flow_correlation", "iat_cv": "login_iat_cv", "failure_ratio": "auth_failure_ratio"}
    for key, channel in mapping.items():
        kpis[channel] = scenario.baselines[channel] * (1.0 - share) + attack.population_profile[key] * share
    kpis["watch_time_index"] = scenario.baselines["watch_time_index"]
    kpis["conversion_coherence"] = scenario.baselines["conversion_coherence"]


def _is_active(ts: datetime, start: datetime, end: datetime) -> bool:
    return start <= ts <= end


def _smoothstep(value: float) -> float:
    clipped = min(1.0, max(0.0, value))
    return clipped * clipped * (3.0 - 2.0 * clipped)
