from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.models import Scenario


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
    _validate_iso_utc_timestamps(payload)
    try:
        scenario = Scenario.model_validate(payload)
    except ValidationError:
        raise
    _validate_scenario_references(scenario)
    return _normalize_datetimes(scenario)


def _validate_iso_utc_timestamps(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            next_path = f"{path}.{key}"
            if key in TIMESTAMP_FIELDS:
                _require_iso_utc_string(nested, next_path)
            else:
                _validate_iso_utc_timestamps(nested, next_path)
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            next_path = f"{path}[{index}]"
            if _looks_like_timestamp_list(path):
                _require_iso_utc_string(nested, next_path)
            else:
                _validate_iso_utc_timestamps(nested, next_path)


def _looks_like_timestamp_list(path: str) -> bool:
    return path.endswith(".goals")


def _require_iso_utc_string(value: Any, path: str) -> None:
    if not isinstance(value, str) or not value.endswith("Z") or "T" not in value:
        raise ValueError(f"{path} must be an ISO-8601 UTC timestamp ending in Z")
    datetime.fromisoformat(value.replace("Z", "+00:00"))


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
        if event.end <= event.start:
            raise ValueError(f"event {event.id} must end after it starts")
        for impact in event.expected_impacts:
            if impact.kpi not in kpi_ids:
                raise ValueError(f"event {event.id} references unknown KPI {impact.kpi}")
            if impact.low <= 0 or impact.high < impact.low:
                raise ValueError(f"event {event.id} has invalid range for {impact.kpi}")
        if event.kind == "match":
            if event.kickoff is None or event.full_time is None or event.pre_ramp_start is None:
                raise ValueError(f"match {event.id} requires kickoff/full_time/pre_ramp_start")
    for attack in scenario.attacks:
        if attack.end <= attack.start:
            raise ValueError(f"attack {attack.id} must end after it starts")
        if attack.target_kpi not in kpi_ids:
            raise ValueError(f"attack {attack.id} references unknown KPI {attack.target_kpi}")
        for impact in attack.additive_impacts:
            if impact.kpi not in kpi_ids:
                raise ValueError(f"attack {attack.id} references unknown KPI {impact.kpi}")
