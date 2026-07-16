from __future__ import annotations

from collections import defaultdict
import os

from app.actions import maybe_act
from app.detector import run_detector
from app.envelope import run_envelope_detector
from app.generator import generate_ticks
from app.models import ActionRecord, Decision, DetectorTick, Scenario, Tick, Timeline
from app.rca import build_rca_records


def build_timeline(scenario: Scenario, seed: int | None = None) -> Timeline:
    ghost_ticks = generate_ticks(scenario, seed=seed)
    detector_mode = os.environ.get("DETECTOR", "envelope").lower()
    _, first_pass = _run_detector(scenario, ghost_ticks, detector_mode)
    actions = [action for decision in first_pass if (action := maybe_act(decision)) is not None]
    action_start = actions[0].ts if actions else None
    ticks = generate_ticks(scenario, seed=seed, action_start_ts=action_start)
    for actual, ghost in zip(ticks, ghost_ticks):
        actual.ghost_kpis = ghost.kpis
    ticks, decisions = _run_detector(scenario, ticks, detector_mode)
    _set_mttr(scenario, ticks, actions)
    return Timeline(
        scenario=scenario.name,
        ticks=ticks,
        decisions=decisions,
        actions=actions,
        rca_records=build_rca_records(decisions, actions),
    )


def _run_detector(
    scenario: Scenario, ticks: list[Tick], detector_mode: str
) -> tuple[list[Tick], list[Decision]]:
    if detector_mode == "rules":
        detector_ticks = [
            DetectorTick(ts=tick.ts, kpis=tick.kpis, active_events=tick.active_events)
            for tick in ticks
        ]
        return ticks, run_detector(scenario, detector_ticks)
    elif detector_mode == "envelope":
        return run_envelope_detector(scenario, ticks)
    else:
        raise ValueError("DETECTOR must be envelope or rules")


def _set_mttr(scenario: Scenario, ticks: list[Tick], actions: list[ActionRecord]) -> None:
    baseline = scenario.baselines["auth_login_rps"]
    for action in actions:
        for tick in ticks:
            if tick.ts >= action.ts and tick.kpis["auth_login_rps"] < baseline * 2:
                action.mttr_seconds = int((tick.ts - action.ts).total_seconds())
                break


def decisions_by_timestamp(decisions: list[Decision]) -> dict[str, list[Decision]]:
    grouped: dict[str, list[Decision]] = defaultdict(list)
    for decision in decisions:
        grouped[decision.ts.isoformat()].append(decision)
    return dict(grouped)


def public_tick(tick: Tick) -> dict:
    return tick.model_dump(mode="json", exclude={"truth"}, exclude_none=True)
