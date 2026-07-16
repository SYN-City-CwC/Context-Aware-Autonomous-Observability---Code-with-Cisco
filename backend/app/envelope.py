from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import pi, sin
from pathlib import Path
from typing import Any, Sequence

import lightgbm as lgb
import numpy as np

from app.features import build_feature_row
from app.models import Decision, DeclaredRange, EnvelopeBand, Evidence, EventSpec, Scenario, Tick
from app.scenario import all_context_events
from app.train import DEFAULT_MODEL_DIR


EPS = 1e-9


@dataclass
class AlertState:
    active: bool = False
    breach_ticks: int = 0
    clear_ticks: int = 0


@dataclass
class SuppressState:
    active: bool = False
    breach_ticks: int = 0
    clear_ticks: int = 0


@dataclass(frozen=True)
class KpiModels:
    p10: lgb.Booster
    p50: lgb.Booster
    p90: lgb.Booster
    blind_p90: lgb.Booster
    feature_names: list[str]
    blind_feature_names: list[str]


@dataclass(frozen=True)
class ModelBundle:
    models: dict[str, KpiModels]
    meta: dict[str, Any]


def run_envelope_detector(
    scenario: Scenario,
    ticks: Sequence[Tick],
    *,
    model_dir: Path | None = None,
) -> tuple[list[Tick], list[Decision]]:
    bundle = load_model_bundle(model_dir or DEFAULT_MODEL_DIR)
    events = all_context_events(scenario)
    decisions: list[Decision] = []
    alert_states = {kpi.id: AlertState() for kpi in scenario.kpis}
    suppress_states = {kpi.id: SuppressState() for kpi in scenario.kpis}
    feature_values: dict[str, dict[Any, float]] = defaultdict(dict)

    for tick in ticks:
        envelope: dict[str, EnvelopeBand] = {}
        p50_by_kpi: dict[str, float] = {}
        for kpi in scenario.kpis:
            kpi_models = bundle.models[kpi.id]
            row = build_feature_row(
                scenario=scenario,
                ts=tick.ts,
                kpi_id=kpi.id,
                active_event_ids=tick.active_events,
                values_by_ts=feature_values[kpi.id],
                events=events,
                include_context=True,
            )
            blind_row = build_feature_row(
                scenario=scenario,
                ts=tick.ts,
                kpi_id=kpi.id,
                active_event_ids=tick.active_events,
                values_by_ts=feature_values[kpi.id],
                events=events,
                include_context=False,
            )
            p10, p50, p90 = _predict_band(kpi_models, row)
            p10, p50, p90 = _adjust_band(
                scenario,
                tick.ts,
                kpi.id,
                [event for event in events if event.id in tick.active_events],
                p10,
                p50,
                p90,
            )
            blind_p90 = _predict(kpi_models.blind_p90, blind_row, kpi_models.blind_feature_names)
            observed = tick.kpis[kpi.id]
            envelope[kpi.id] = EnvelopeBand(p10=round(p10, 6), p90=round(p90, 6))
            p50_by_kpi[kpi.id] = p50
            decision = _advance_alert_episode(
                scenario=scenario,
                tick=tick,
                kpi_id=kpi.id,
                observed=observed,
                p10=p10,
                p50=p50,
                p90=p90,
                blind_p90=blind_p90,
                active_events=[event for event in events if event.id in tick.active_events],
                state=alert_states[kpi.id],
            )
            if decision is not None:
                decisions.append(decision)
            suppress_decision = _advance_suppress_episode(
                tick=tick,
                kpi_id=kpi.id,
                observed=observed,
                p10=p10,
                p50=p50,
                p90=p90,
                blind_p90=blind_p90,
                active_events=[event for event in events if event.id in tick.active_events],
                state=suppress_states[kpi.id],
            )
            if suppress_decision is not None:
                decisions.append(suppress_decision)
        tick.envelope = envelope
        for kpi in scenario.kpis:
            observed = tick.kpis[kpi.id]
            # Anti-poisoning: once an anomaly episode is open, future lag/rolling
            # features use the model's P50 instead of observed values so the
            # envelope cannot absorb an ongoing attack.
            feature_values[kpi.id][tick.ts] = (
                p50_by_kpi[kpi.id] if alert_states[kpi.id].active else observed
            )
    return list(ticks), decisions


def load_model_bundle(model_dir: Path) -> ModelBundle:
    meta_path = model_dir / "meta.json"
    if not meta_path.exists():
        raise RuntimeError("run python -m app.train")
    with meta_path.open("r", encoding="utf-8") as handle:
        meta = json.load(handle)
    models: dict[str, KpiModels] = {}
    for kpi_id, model_info in meta["models"].items():
        models[kpi_id] = KpiModels(
            p10=lgb.Booster(model_file=str(model_dir / model_info["p10"])),
            p50=lgb.Booster(model_file=str(model_dir / model_info["p50"])),
            p90=lgb.Booster(model_file=str(model_dir / model_info["p90"])),
            blind_p90=lgb.Booster(model_file=str(model_dir / model_info["blind_p90"])),
            feature_names=meta["feature_names"][kpi_id],
            blind_feature_names=model_info["blind_feature_names"],
        )
    return ModelBundle(models=models, meta=meta)


def _advance_alert_episode(
    scenario: Scenario,
    tick: Tick,
    kpi_id: str,
    observed: float,
    p10: float,
    p50: float,
    p90: float,
    blind_p90: float,
    active_events: list[EventSpec],
    state: AlertState,
) -> Decision | None:
    below = observed < p10
    above = observed > p90
    if not state.active and (below or above):
        state.breach_ticks += 1
        if state.breach_ticks >= 3:
            state.active = True
            state.clear_ticks = 0
            verdict_class = "unexplained-deviation" if above else "unexplained-drop"
            return _alert_decision(
                scenario,
                tick,
                kpi_id,
                observed,
                p10,
                p50,
                p90,
                blind_p90,
                active_events,
                verdict_class,
            )
    elif state.active:
        if p10 <= observed <= p90:
            state.clear_ticks += 1
            if state.clear_ticks >= 3:
                state.active = False
                state.breach_ticks = 0
                state.clear_ticks = 0
        else:
            state.clear_ticks = 0
    else:
        state.breach_ticks = 0
    return None


def _advance_suppress_episode(
    tick: Tick,
    kpi_id: str,
    observed: float,
    p10: float,
    p50: float,
    p90: float,
    blind_p90: float,
    active_events: list[EventSpec],
    state: SuppressState,
) -> Decision | None:
    declared_context = any(
        impact.kpi == kpi_id for event in active_events for impact in event.expected_impacts
    )
    explained_breach = (
        observed > blind_p90 and p10 <= observed <= p90 and declared_context
    )
    if not state.active and explained_breach:
        state.breach_ticks += 1
        if state.breach_ticks >= 3:
            state.active = True
            state.clear_ticks = 0
            return _suppress_decision(
                tick, kpi_id, observed, p10, p50, p90, blind_p90, active_events
            )
    elif state.active:
        if not explained_breach:
            state.clear_ticks += 1
            if state.clear_ticks >= 3:
                state.active = False
                state.breach_ticks = 0
                state.clear_ticks = 0
        else:
            state.clear_ticks = 0
    else:
        state.breach_ticks = 0
    return None


def _alert_decision(
    scenario: Scenario,
    tick: Tick,
    kpi_id: str,
    observed: float,
    p10: float,
    p50: float,
    p90: float,
    blind_p90: float,
    active_events: list[EventSpec],
    verdict_class: str,
) -> Decision:
    if observed > p90:
        z = (observed - p90) / max(p90 - p10, EPS)
    else:
        z = (p10 - observed) / max(p90 - p10, EPS)
    confidence = round(_clip(0.55 + 0.10 * z, 0.55, 0.95), 3)
    context_note = _context_note_for_alert(kpi_id, active_events)
    reason = (
        f"{kpi_id} observed {observed:.2f} outside band "
        f"[{p10:.2f}, {p90:.2f}]; {context_note}; no declared context explains it"
    )
    return Decision(
        ts=tick.ts,
        verdict="ALERT",
        decision_class=verdict_class,
        reason=reason,
        confidence=confidence,
        evidence=_evidence(
            tick, kpi_id, observed, p10, p50, p90, blind_p90, active_events
        ),
    )


def _suppress_decision(
    tick: Tick,
    kpi_id: str,
    observed: float,
    p10: float,
    p50: float,
    p90: float,
    blind_p90: float,
    active_events: list[EventSpec],
) -> Decision:
    confidence = round(
        _clip(0.80 + 0.15 * (1.0 - abs(observed - p50) / max(p90 - p50, EPS)), 0.80, 0.95),
        3,
    )
    event_ids = ", ".join(event.id for event in active_events)
    reason = (
        f"{kpi_id} would have alerted against history; declared context {event_ids} "
        f"explains it; inside context-conditioned envelope "
        f"[{p10:.2f}, {p90:.2f}]"
    )
    return Decision(
        ts=tick.ts,
        verdict="SUPPRESS",
        decision_class="expected-event-traffic",
        reason=reason,
        confidence=confidence,
        evidence=_evidence(
            tick, kpi_id, observed, p10, p50, p90, blind_p90, active_events
        ),
    )


def _evidence(
    tick: Tick,
    kpi_id: str,
    observed: float,
    p10: float,
    p50: float,
    p90: float,
    blind_p90: float,
    active_events: list[EventSpec],
) -> Evidence:
    return Evidence(
        kpi=kpi_id,
        observed=round(observed, 6),
        baseline=round(p50, 6),
        ratio=round(observed / max(p50, EPS), 4),
        active_events=[event.id for event in active_events],
        declared_range=_first_declared_range(kpi_id, active_events),
        p10=round(p10, 6),
        p50=round(p50, 6),
        p90=round(p90, 6),
        context_blind_p90=round(blind_p90, 6),
    )


def _context_note_for_alert(kpi_id: str, active_events: list[EventSpec]) -> str:
    if not active_events:
        return "no declared context is active"
    for event in active_events:
        if any(impact.kpi == kpi_id for impact in event.expected_impacts):
            return f"{event.id} active but {kpi_id} is outside its expected band"
    return (
        f"{', '.join(event.id for event in active_events)} active but {kpi_id} "
        "is outside its declared impact set"
    )


def _first_declared_range(
    kpi_id: str, active_events: list[EventSpec]
) -> DeclaredRange | None:
    for event in active_events:
        for impact in event.expected_impacts:
            if impact.kpi == kpi_id:
                return DeclaredRange(event_id=event.id, low=impact.low, high=impact.high)
    return None


def _predict_band(models: KpiModels, row: dict[str, float]) -> tuple[float, float, float]:
    p10 = _predict(models.p10, row, models.feature_names)
    p50 = _predict(models.p50, row, models.feature_names)
    p90 = _predict(models.p90, row, models.feature_names)
    ordered = sorted([p10, p50, p90])
    return ordered[0], ordered[1], ordered[2]


def _adjust_band(
    scenario: Scenario,
    ts: datetime,
    kpi_id: str,
    active_events: list[EventSpec],
    p10: float,
    p50: float,
    p90: float,
) -> tuple[float, float, float]:
    kpi = next(item for item in scenario.kpis if item.id == kpi_id)
    floor = max(_diurnal_baseline(ts, kpi.baseline, kpi.diurnal), EPS)
    min_width = floor * (0.12 if kpi.unit != "ratio" else 0.35)
    adjusted_p10 = min(p10, p50 - min_width / 2.0)
    adjusted_p90 = max(p90, p50 + min_width / 2.0)
    adjusted_p50 = p50

    low_multiplier = 1.0
    mid_multiplier = 1.0
    high_multiplier = 1.0
    has_declared_context = False
    for event in active_events:
        shape = _event_shape(event, ts)
        if shape <= 0:
            continue
        for impact in event.expected_impacts:
            if impact.kpi != kpi_id:
                continue
            has_declared_context = True
            low_multiplier *= 1.0 + (impact.low - 1.0) * shape
            mid_multiplier *= 1.0 + (((impact.low + impact.high) / 2.0) - 1.0) * shape
            high_multiplier *= 1.0 + (impact.high - 1.0) * shape
    if has_declared_context:
        adjusted_p10 = min(adjusted_p10, floor * low_multiplier * 0.9)
        adjusted_p50 = max(adjusted_p50, floor * mid_multiplier)
        adjusted_p90 = max(adjusted_p90, floor * high_multiplier * 1.08)
    adjusted_p10 = max(0.0, adjusted_p10)
    if adjusted_p90 <= adjusted_p10:
        adjusted_p90 = adjusted_p10 + max(min_width, EPS)
    adjusted_p50 = min(max(adjusted_p50, adjusted_p10), adjusted_p90)
    return adjusted_p10, adjusted_p50, adjusted_p90


def _diurnal_baseline(ts: datetime, baseline: float, amplitude: float) -> float:
    if amplitude <= 0.0:
        return baseline
    minute = ts.hour * 60 + ts.minute + ts.second / 60.0
    phase = 2.0 * pi * (minute - 14 * 60) / (24 * 60)
    return baseline * (1.0 + amplitude * sin(phase))


def _event_shape(event: EventSpec, ts: datetime) -> float:
    if event.kind == "match":
        if event.pre_ramp_start is None or event.kickoff is None or event.full_time is None:
            return 0.0
        if ts < event.pre_ramp_start or ts > event.full_time:
            return 0.0
        if ts < event.kickoff:
            total = (event.kickoff - event.pre_ramp_start).total_seconds()
            elapsed = (ts - event.pre_ramp_start).total_seconds()
            return _smoothstep(elapsed / total)
        return 1.0
    tail_seconds = 150.0
    if ts < event.start or ts > event.end + timedelta(seconds=tail_seconds):
        return 0.0
    if ts <= event.end:
        return min(1.0, max(0.0, (ts - event.start).total_seconds() / 10.0))
    return 0.0


def _smoothstep(value: float) -> float:
    clipped = min(1.0, max(0.0, value))
    return clipped * clipped * (3.0 - 2.0 * clipped)


def _predict(model: lgb.Booster, row: dict[str, float], feature_names: list[str]) -> float:
    values = np.array([[row[feature] for feature in feature_names]], dtype=float)
    return float(model.predict(values)[0])


def _clip(value: float, low: float, high: float) -> float:
    return min(high, max(low, value))
