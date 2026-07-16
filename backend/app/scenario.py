from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.models import EventSpec, PriorEventSpec, Scenario


DEFAULT_SCENARIO_PATH = Path(__file__).resolve().parents[1] / "scenarios" / "the-final.json"


TIMESTAMP_FIELDS = {
    "sim_start",
    "sim_end",
    "start",
    "end",
    "kickoff",
    "full_time",
    "pre_ramp_start",
}


def scenario_path_from_env() -> Path:
    return Path(os.environ.get("SCENARIO_PATH", str(DEFAULT_SCENARIO_PATH)))


def load_scenario(path: str | Path | None = None) -> Scenario:
    scenario_path = Path(path) if path is not None else scenario_path_from_env()
    with scenario_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    _validate_timestamps(payload)
    scenario = Scenario.model_validate(payload)
    _validate_scenario_references(scenario)
    return _normalize_datetimes(scenario)


def resolve_prior_events(scenario: Scenario) -> list[EventSpec]:
    if scenario.history is None:
        return []
    return [_resolve_prior_event(scenario, event) for event in scenario.history.prior_events]


def all_context_events(scenario: Scenario) -> list[EventSpec]:
    return [*resolve_prior_events(scenario), *scenario.events]


def _validate_timestamps(value: Any, path: str = "$", prior_event: bool = False) -> None:
    if isinstance(value, dict):
        in_prior_event = prior_event or "day_offset" in value
        for key, nested in value.items():
            next_path = f"{path}.{key}"
            if key in TIMESTAMP_FIELDS and in_prior_event:
                _require_time_of_day_string(nested, next_path)
            elif key in TIMESTAMP_FIELDS:
                _require_iso_utc_string(nested, next_path)
            else:
                _validate_timestamps(nested, next_path, in_prior_event)
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            next_path = f"{path}[{index}]"
            if _looks_like_timestamp_list(path) and prior_event:
                _require_time_of_day_string(nested, next_path)
            elif _looks_like_timestamp_list(path):
                _require_iso_utc_string(nested, next_path)
            else:
                _validate_timestamps(nested, next_path, prior_event)


def _looks_like_timestamp_list(path: str) -> bool:
    return path.endswith(".goals")


def _require_iso_utc_string(value: Any, path: str) -> None:
    if not isinstance(value, str) or not value.endswith("Z") or "T" not in value:
        raise ValueError(f"{path} must be an ISO-8601 UTC timestamp ending in Z")
    datetime.fromisoformat(value.replace("Z", "+00:00"))


def _require_time_of_day_string(value: Any, path: str) -> None:
    if not isinstance(value, str):
        raise ValueError(f"{path} must be an HH:MM or HH:MM:SS time-of-day")
    _parse_time_of_day(value, path)


def _normalize_datetimes(scenario: Scenario) -> Scenario:
    payload = scenario.model_dump()
    return Scenario.model_validate(_normalize_value(payload))


def _normalize_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(UTC)
    if isinstance(value, dict):
        return {key: _normalize_value(nested) for key, nested in value.items()}
    if isinstance(value, list):
        return [_normalize_value(nested) for nested in value]
    return value


def _validate_scenario_references(scenario: Scenario) -> None:
    kpi_ids = {kpi.id for kpi in scenario.kpis}
    if scenario.sim_end <= scenario.sim_start:
        raise ValueError("sim_end must be after sim_start")
    if scenario.tick_seconds <= 0:
        raise ValueError("tick_seconds must be positive")
    for event in scenario.events:
        _validate_event_spec(event, kpi_ids)
    if scenario.history is not None:
        if scenario.history.days < 2:
            raise ValueError("history.days must include training days plus match day")
        for event in scenario.history.prior_events:
            _validate_prior_event_spec(event, kpi_ids)
    for attack in scenario.attacks:
        if attack.end <= attack.start:
            raise ValueError(f"attack {attack.id} must end after it starts")
        if attack.target_kpi not in kpi_ids:
            raise ValueError(f"attack {attack.id} references unknown KPI {attack.target_kpi}")
        for impact in attack.additive_impacts:
            if impact.kpi not in kpi_ids:
                raise ValueError(f"attack {attack.id} references unknown KPI {impact.kpi}")


def _validate_event_spec(event: EventSpec, kpi_ids: set[str]) -> None:
    if event.end <= event.start:
        raise ValueError(f"event {event.id} must end after it starts")
    _validate_impacts(event.id, event.expected_impacts, kpi_ids)
    if event.goal_impact is not None:
        if event.goal_impact.kpi not in kpi_ids:
            raise ValueError(f"event {event.id} has unknown goal impact KPI")
        if event.goal_impact.low <= 0 or event.goal_impact.high < event.goal_impact.low:
            raise ValueError(f"event {event.id} has invalid goal impact range")
        if (
            event.goal_impact.decay_seconds_low <= 0
            or event.goal_impact.decay_seconds_high < event.goal_impact.decay_seconds_low
        ):
            raise ValueError(f"event {event.id} has invalid goal decay range")
    if event.kind == "match":
        if event.kickoff is None or event.full_time is None or event.pre_ramp_start is None:
            raise ValueError(f"match {event.id} requires kickoff/full_time/pre_ramp_start")


def _validate_prior_event_spec(event: PriorEventSpec, kpi_ids: set[str]) -> None:
    if event.day_offset >= 0:
        raise ValueError(f"prior event {event.id} day_offset must be negative")
    if _parse_time_of_day(event.end, f"{event.id}.end") <= _parse_time_of_day(
        event.start, f"{event.id}.start"
    ):
        raise ValueError(f"prior event {event.id} must end after it starts")
    _validate_impacts(event.id, event.expected_impacts, kpi_ids)
    if event.kind == "match":
        if event.kickoff is None or event.full_time is None or event.pre_ramp_start is None:
            raise ValueError(f"prior match {event.id} requires kickoff/full_time/pre_ramp_start")


def _validate_impacts(event_id: str, impacts: list[Any], kpi_ids: set[str]) -> None:
    for impact in impacts:
        if impact.kpi not in kpi_ids:
            raise ValueError(f"event {event_id} references unknown KPI {impact.kpi}")
        if impact.low <= 0 or impact.high < impact.low:
            raise ValueError(f"event {event_id} has invalid range for {impact.kpi}")


def _resolve_prior_event(scenario: Scenario, event: PriorEventSpec) -> EventSpec:
    base_date = scenario.sim_start.date()
    return EventSpec(
        kind=event.kind,
        id=event.id,
        start=_resolve_time(base_date, event.day_offset, event.start),
        end=_resolve_time(base_date, event.day_offset, event.end),
        expected_impacts=event.expected_impacts,
        kickoff=_resolve_time(base_date, event.day_offset, event.kickoff)
        if event.kickoff is not None
        else None,
        full_time=_resolve_time(base_date, event.day_offset, event.full_time)
        if event.full_time is not None
        else None,
        pre_ramp_start=_resolve_time(base_date, event.day_offset, event.pre_ramp_start)
        if event.pre_ramp_start is not None
        else None,
        goals=[_resolve_time(base_date, event.day_offset, goal) for goal in event.goals],
        goal_impact=event.goal_impact,
    )


def _resolve_time(base_date: Any, day_offset: int, time_value: str) -> datetime:
    from datetime import date, time, timedelta

    if not isinstance(base_date, date):
        raise TypeError("base_date must be a date")
    parts = _parse_time_of_day(time_value, time_value)
    resolved_date = base_date + timedelta(days=day_offset)
    return datetime.combine(resolved_date, time(*parts), tzinfo=UTC)


def _parse_time_of_day(value: str, path: str) -> tuple[int, int, int]:
    parts = value.split(":")
    if len(parts) not in (2, 3):
        raise ValueError(f"{path} must be HH:MM or HH:MM:SS")
    hour, minute = int(parts[0]), int(parts[1])
    second = int(parts[2]) if len(parts) == 3 else 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59):
        raise ValueError(f"{path} must be a valid time-of-day")
    return hour, minute, second
