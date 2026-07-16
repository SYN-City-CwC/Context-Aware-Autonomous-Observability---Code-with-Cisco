from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import cos, pi, sin

import pandas as pd

from app.models import EventSpec, Scenario, Tick
from app.scenario import all_context_events


LAG_MINUTES = (1, 2, 3, 6, 12, 30, 60)
CONTEXT_FEATURES = {
    "match_live",
    "minutes_to_kickoff",
    "minutes_since_goal",
    "campaign_active",
    "expected_multiplier_mid",
}


@dataclass(frozen=True)
class FeatureBuild:
    frame: pd.DataFrame
    target: pd.Series
    feature_names: list[str]


def build_feature_frame(
    scenario: Scenario,
    ticks: Sequence[Tick],
    kpi_id: str,
    *,
    include_context: bool = True,
    value_overrides: dict[datetime, float] | None = None,
) -> FeatureBuild:
    events = all_context_events(scenario)
    timestamps = [tick.ts for tick in ticks]
    values_by_ts = {
        tick.ts: tick.kpis[kpi_id] for tick in ticks if kpi_id in tick.kpis
    }
    if value_overrides:
        values_by_ts.update(value_overrides)
    baseline = scenario.baselines[kpi_id]
    frame = pd.DataFrame(index=pd.DatetimeIndex(timestamps))
    for minutes in LAG_MINUTES:
        frame[f"lag_{minutes}m"] = [
            _value_at(values_by_ts, ts - timedelta(minutes=minutes), baseline)
            for ts in timestamps
        ]
    frame["lag_24h"] = [
        _value_at(values_by_ts, ts - timedelta(hours=24), baseline) for ts in timestamps
    ]
    ordered = pd.Series([values_by_ts[ts] for ts in timestamps], index=frame.index)
    previous = ordered.shift(1)
    five_ticks = max(1, int((5 * 60) / scenario.tick_seconds))
    thirty_ticks = max(1, int((30 * 60) / scenario.tick_seconds))
    frame["rolling_mean_5m"] = previous.rolling(five_ticks, min_periods=1).mean().fillna(baseline)
    frame["rolling_std_5m"] = previous.rolling(five_ticks, min_periods=1).std(ddof=0).fillna(0.0)
    frame["rolling_mean_30m"] = previous.rolling(thirty_ticks, min_periods=1).mean().fillna(baseline)
    frame["rolling_std_30m"] = previous.rolling(thirty_ticks, min_periods=1).std(ddof=0).fillna(0.0)
    frame["rate_of_change_1m"] = (
        (frame["lag_1m"] - frame["lag_2m"]) / frame["lag_2m"].clip(lower=1e-9)
    )
    minutes_of_day = pd.Series(
        [ts.hour * 60 + ts.minute + ts.second / 60.0 for ts in timestamps],
        index=frame.index,
    )
    angle = 2.0 * pi * minutes_of_day / (24 * 60)
    frame["minute_sin"] = angle.map(sin)
    frame["minute_cos"] = angle.map(cos)
    frame["day_of_week"] = [float(ts.weekday()) for ts in timestamps]
    if include_context:
        context_rows = [
            _context_features(tick.ts, kpi_id, tick.active_events, events) for tick in ticks
        ]
        frame = pd.concat([frame, pd.DataFrame(context_rows, index=frame.index)], axis=1)
    target = pd.Series([tick.kpis[kpi_id] for tick in ticks], name=kpi_id)
    frame = frame.reset_index(drop=True)
    return FeatureBuild(frame=frame, target=target.reset_index(drop=True), feature_names=list(frame.columns))


def build_feature_row(
    scenario: Scenario,
    ts: datetime,
    kpi_id: str,
    active_event_ids: list[str],
    values_by_ts: dict[datetime, float],
    events: Sequence[EventSpec],
    *,
    include_context: bool = True,
) -> dict[str, float]:
    baseline = scenario.baselines[kpi_id]
    row: dict[str, float] = {}
    for minutes in LAG_MINUTES:
        row[f"lag_{minutes}m"] = _value_at(values_by_ts, ts - timedelta(minutes=minutes), baseline)
    row["lag_24h"] = _value_at(values_by_ts, ts - timedelta(hours=24), baseline)
    row["rolling_mean_5m"] = _rolling_stat(values_by_ts, ts, baseline, minutes=5, stat="mean")
    row["rolling_std_5m"] = _rolling_stat(values_by_ts, ts, baseline, minutes=5, stat="std")
    row["rolling_mean_30m"] = _rolling_stat(values_by_ts, ts, baseline, minutes=30, stat="mean")
    row["rolling_std_30m"] = _rolling_stat(values_by_ts, ts, baseline, minutes=30, stat="std")
    previous = row["lag_2m"]
    row["rate_of_change_1m"] = (row["lag_1m"] - previous) / max(previous, 1e-9)
    minute = ts.hour * 60 + ts.minute + ts.second / 60.0
    angle = 2.0 * pi * minute / (24 * 60)
    row["minute_sin"] = sin(angle)
    row["minute_cos"] = cos(angle)
    row["day_of_week"] = float(ts.weekday())
    if include_context:
        row.update(_context_features(ts, kpi_id, active_event_ids, events))
    return row


def _context_features(
    ts: datetime, kpi_id: str, active_event_ids: list[str], events: Sequence[EventSpec]
) -> dict[str, float]:
    event_by_id = {event.id: event for event in events}
    active_events = [event_by_id[event_id] for event_id in active_event_ids if event_id in event_by_id]
    matches_today = [
        event for event in events if event.kind == "match" and event.start.date() == ts.date()
    ]
    match_live = any(event.kind == "match" for event in active_events)
    campaigns = [event for event in active_events if event.kind == "campaign"]
    mids = [
        (impact.low + impact.high) / 2.0
        for event in active_events
        for impact in event.expected_impacts
        if impact.kpi == kpi_id
    ]
    return {
        "match_live": 1.0 if match_live else 0.0,
        "minutes_to_kickoff": _minutes_to_kickoff(ts, matches_today),
        "minutes_since_goal": _minutes_since_goal(ts, matches_today),
        "campaign_active": 1.0 if campaigns else 0.0,
        "expected_multiplier_mid": max(mids) if mids else 1.0,
    }


def _minutes_to_kickoff(ts: datetime, matches_today: list[EventSpec]) -> float:
    kickoffs = [event.kickoff for event in matches_today if event.kickoff is not None]
    if not kickoffs:
        return 9999.0
    value = min((kickoff - ts).total_seconds() / 60.0 for kickoff in kickoffs)
    return float(min(360.0, max(-180.0, value)))


def _minutes_since_goal(ts: datetime, matches_today: list[EventSpec]) -> float:
    prior_goals = [goal for event in matches_today for goal in event.goals if goal <= ts]
    if not prior_goals:
        return 9999.0
    value = (ts - max(prior_goals)).total_seconds() / 60.0
    return float(min(240.0, max(0.0, value)))


def _value_at(values_by_ts: dict[datetime, float], ts: datetime, fallback: float) -> float:
    return float(values_by_ts.get(ts, fallback))


def _rolling_stat(
    values_by_ts: dict[datetime, float],
    ts: datetime,
    fallback: float,
    *,
    minutes: int,
    stat: str,
) -> float:
    start = ts - timedelta(minutes=minutes)
    values = [
        value
        for value_ts, value in values_by_ts.items()
        if start <= value_ts < ts
    ]
    if not values:
        return fallback if stat == "mean" else 0.0
    series = pd.Series(values, dtype="float64")
    if stat == "mean":
        return float(series.mean())
    return float(series.std(ddof=0))
