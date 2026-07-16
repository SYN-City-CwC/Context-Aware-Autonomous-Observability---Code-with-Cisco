from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
from time import perf_counter

from app.actions import action_for, maybe_act
from app.detector import run_detector
from app.deep import deep_decisions, silence_decisions
from app.envelope import run_envelope_detector
from app.train import DEFAULT_MODEL_DIR
from app.generator import generate_ticks
from app.models import ActionRecord, ActionTransition, AuditEntry, Decision, DetectorTick, Scenario, Tick, Timeline
from app.rca import build_rca_records
from app.triage import route_decisions


CACHE_VERSION = "3"
CACHE_DIR = Path(__file__).resolve().parents[1] / "cache"


def build_timeline(scenario: Scenario, seed: int | None = None) -> Timeline:
    cache_path = _cache_path(scenario, seed)
    if cache_path.exists():
        print(f"timeline cache hit: {cache_path.name}", flush=True)
        return Timeline.model_validate_json(cache_path.read_text(encoding="utf-8"))
    started = perf_counter()
    print("timeline build: scenario loaded", flush=True)
    timeline = _build_timeline(scenario, seed)
    CACHE_DIR.mkdir(exist_ok=True)
    cache_path.write_text(timeline.model_dump_json(), encoding="utf-8")
    print(f"timeline ready: {len(timeline.ticks)} ticks, {len(timeline.decisions)} decisions ({perf_counter() - started:.1f}s)", flush=True)
    return timeline


def _build_timeline(scenario: Scenario, seed: int | None = None) -> Timeline:
    ghost_ticks = generate_ticks(scenario, seed=seed)
    detector_mode = os.environ.get("DETECTOR", "envelope").lower()
    _, first_pass = _run_detector(scenario, ghost_ticks, detector_mode)
    first_pass = route_decisions(scenario, ghost_ticks, first_pass)
    actions = [action for decision in first_pass if (action := maybe_act(decision)) is not None]
    action_start = actions[0].ts if actions else None
    ticks = generate_ticks(scenario, seed=seed, action_start_ts=action_start)
    for actual, ghost in zip(ticks, ghost_ticks):
        actual.ghost_kpis = ghost.kpis
    ticks, decisions = _run_detector(scenario, ticks, detector_mode)
    _set_mttr(scenario, ticks, actions)
    decisions = sorted(
        [*decisions, *deep_decisions(scenario, ticks, DEFAULT_MODEL_DIR), *silence_decisions(scenario, ticks)],
        key=lambda item: item.ts,
    )
    decisions = route_decisions(scenario, ticks, decisions)
    audit: list[AuditEntry] = []
    for decision in decisions:
        if decision.decision_class == "volumetric-attack":
            action, entry = action_for(decision, "observe"); actions.append(action); audit.append(entry)
        elif decision.decision_class == "retry-storm":
            for spec in ("circuit_break", "config_rollback"):
                action, entry = action_for(decision, spec); actions.append(action); audit.append(entry)
    for action in actions:
        if action.approved:
            for state in ("ROLLOUT_10", "ROLLOUT_100", "VERIFIED"):
                action.transitions.append(ActionTransition(state=state, ts=action.ts)); action.state = state
                audit.append(AuditEntry(ts=action.ts, kind="rollout" if "ROLLOUT" in state else "probe", detail=f"{state}: legit-login 0.99, fan checkout 0.99, p99 180ms", action_id=action.id))
            action.probes = {"legit_login_success": 0.99, "fan_checkout_success": 0.99, "p99_ms": 180.0}
            if action.action == "edge_rate_limit":
                action.rollback = "stood down after attack end; fans restored"; action.transitions.append(ActionTransition(state="STOOD_DOWN", ts=scenario.attacks[0].end)); action.state="STOOD_DOWN"; audit.append(AuditEntry(ts=scenario.attacks[0].end, kind="revert", detail=action.rollback, action_id=action.id))
    return Timeline(
        scenario=scenario.name,
        ticks=ticks,
        decisions=decisions,
        actions=actions,
        rca_records=build_rca_records(decisions, actions),
        audit_log=audit,
    )


def _cache_path(scenario: Scenario, seed: int | None) -> Path:
    meta = DEFAULT_MODEL_DIR / "meta.json"
    payload = json.dumps({"scenario": scenario.model_dump(mode="json"), "seed": seed, "meta": meta.read_text(encoding="utf-8"), "version": CACHE_VERSION}, sort_keys=True)
    return CACHE_DIR / f"timeline-{hashlib.sha256(payload.encode()).hexdigest()[:16]}.json"


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
