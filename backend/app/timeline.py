from __future__ import annotations

from collections import defaultdict
import os

from app.detector import run_detector
from app.envelope import run_envelope_detector
from app.generator import generate_ticks
from app.models import Decision, DetectorTick, Scenario, Tick, Timeline


def build_timeline(scenario: Scenario, seed: int | None = None) -> Timeline:
    ticks = generate_ticks(scenario, seed=seed)
    detector_mode = os.environ.get("DETECTOR", "envelope").lower()
    if detector_mode == "rules":
        detector_ticks = [
            DetectorTick(ts=tick.ts, kpis=tick.kpis, active_events=tick.active_events)
            for tick in ticks
        ]
        decisions = run_detector(scenario, detector_ticks)
    elif detector_mode == "envelope":
        ticks, decisions = run_envelope_detector(scenario, ticks)
    else:
        raise ValueError("DETECTOR must be envelope or rules")
    return Timeline(scenario=scenario.name, ticks=ticks, decisions=decisions)


def decisions_by_timestamp(decisions: list[Decision]) -> dict[str, list[Decision]]:
    grouped: dict[str, list[Decision]] = defaultdict(list)
    for decision in decisions:
        grouped[decision.ts.isoformat()].append(decision)
    return dict(grouped)


def public_tick(tick: Tick) -> dict:
    return tick.model_dump(mode="json", exclude={"truth"}, exclude_none=True)
