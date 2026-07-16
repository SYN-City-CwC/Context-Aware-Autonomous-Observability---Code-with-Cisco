from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
from time import perf_counter

from app.actions import action_for
from app.detector import run_detector
from app.deep import deep_decisions, silence_decisions
from app.envelope import run_envelope_detector
from app.train import DEFAULT_MODEL_DIR
from app.generator import generate_ticks
from app.models import ActionRecord, ActionTransition, AuditEntry, Decision, DetectorTick, Scenario, Tick, Timeline
from app.rca import build_rca_records
from app.triage import route_decisions


CACHE_VERSION = "4"
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
    actions, applied, audit = _plan_actions(scenario, first_pass, ghost_ticks)
    ticks = generate_ticks(scenario, seed=seed, applied_actions=applied)
    for actual, ghost in zip(ticks, ghost_ticks):
        actual.ghost_kpis = ghost.kpis
    ticks, decisions = _run_detector(scenario, ticks, detector_mode)
    _finalize_probes(scenario, ticks, actions, audit)
    decisions = sorted(
        [*decisions, *deep_decisions(scenario, ticks, DEFAULT_MODEL_DIR), *silence_decisions(scenario, ticks)],
        key=lambda item: item.ts,
    )
    decisions = route_decisions(scenario, ticks, decisions)
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


def _plan_actions(scenario: Scenario, decisions: list[Decision], ticks: list[Tick]) -> tuple[list[ActionRecord], list[dict], list[AuditEntry]]:
    actions: list[ActionRecord] = []; applied: list[dict] = []; audit: list[AuditEntry] = []
    step = scenario.tick_seconds
    for decision in decisions:
        specs = {"credential-stuffing": ["edge_rate_limit"], "volumetric-attack": ["observe"], "retry-storm": ["circuit_break", "config_rollback"]}.get(decision.decision_class, [])
        for spec in specs:
            action, entry = action_for(decision, spec); actions.append(action); audit.append(entry)
            if action.approved and spec == "edge_rate_limit":
                t10 = decision.ts + timedelta(seconds=step); t100 = decision.ts + timedelta(seconds=4 * step)
                action.transitions.extend([ActionTransition(state="ROLLOUT_10", ts=t10), ActionTransition(state="ROLLOUT_100", ts=t100)])
                applied.extend([{"kind":spec,"ts":t10,"fraction":0.1},{"kind":spec,"ts":t100,"fraction":0.8}])
            elif action.approved and spec == "circuit_break":
                t10 = decision.ts + timedelta(seconds=step); action.transitions.append(ActionTransition(state="ROLLOUT_10", ts=t10)); applied.append({"kind":spec,"ts":t10,"fraction":1.0})
    return actions, applied, audit


def _finalize_probes(scenario: Scenario, ticks: list[Tick], actions: list[ActionRecord], audit: list[AuditEntry]) -> None:
    for action in actions:
        if not action.approved:
            continue
        probe_ts = action.ts + timedelta(seconds=3 * scenario.tick_seconds)
        tick = next(item for item in ticks if item.ts >= probe_ts)
        probes = {"legit_login_success": round(1.0 - tick.kpis["auth_failure_ratio"], 4), "fan_checkout_success": round(tick.kpis["conversion_coherence"], 4), "p99_ms": round(tick.kpis["p99_latency_ms"], 2)}
        action.probes = probes; audit.append(AuditEntry(ts=tick.ts, kind="probe", detail=f"legit-login={probes['legit_login_success']:.4f}, fan-checkout={probes['fan_checkout_success']:.4f}, p99={probes['p99_ms']:.2f}ms", action_id=action.id))
        verified_ts = action.ts + timedelta(seconds=5 * scenario.tick_seconds)
        action.transitions.append(ActionTransition(state="VERIFIED", ts=verified_ts)); action.state="VERIFIED"; action.mttr_seconds=int((verified_ts-action.ts).total_seconds())
        if action.action == "edge_rate_limit":
            end = scenario.attacks[0].end; action.transitions.append(ActionTransition(state="STOOD_DOWN", ts=end)); action.state="STOOD_DOWN"; action.rollback="stood down after attack end; probe confirms fans restored"; audit.append(AuditEntry(ts=end,kind="revert",detail=action.rollback,action_id=action.id))


def decisions_by_timestamp(decisions: list[Decision]) -> dict[str, list[Decision]]:
    grouped: dict[str, list[Decision]] = defaultdict(list)
    for decision in decisions:
        grouped[decision.ts.isoformat()].append(decision)
    return dict(grouped)


def public_tick(tick: Tick) -> dict:
    return tick.model_dump(mode="json", exclude={"truth"}, exclude_none=True)
