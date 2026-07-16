from __future__ import annotations

from app.attack_leaf import classify_attack
from app.fault_leaf import classify_fault
from app.models import Decision, Scenario, Tick


def route_decisions(scenario: Scenario, ticks: list[Tick], decisions: list[Decision]) -> list[Decision]:
    by_ts = {tick.ts: tick for tick in ticks}
    for decision in decisions:
        if decision.verdict != "ALERT":
            continue
        tick = by_ts.get(decision.ts)
        if tick is None:
            continue
        if classify_attack(decision, tick, scenario) is None:
            classify_fault(decision, tick, scenario)
    return decisions
