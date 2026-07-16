from __future__ import annotations

from app.models import Decision, Scenario, Tick


def classify_fault(decision: Decision, tick: Tick, scenario: Scenario) -> Decision | None:
    if tick.kpis.get("retry_amplification", 1.0) > 1.5:
        deploy = max((item for item in scenario.deployments if item.service == "checkout-svc" and item.ts <= decision.ts), key=lambda item: item.ts, default=None)
        if deploy is not None:
            change = deploy.change
            decision.decision_class = "retry-storm"
            decision.leaf = "fault"
            decision.confidence = 0.9
            decision.reason = f"retry amplification {tick.kpis['retry_amplification']:.2f}x; memory slope flat; correlated deploy {deploy.service} {deploy.version} at {deploy.ts.strftime('%H:%M')} set {change.file}:{change.line} {change.key} {change.old:.0f}->{change.new:.0f} within 60 min - verdict: retry storm."
            return decision
    if decision.evidence.kpi == "memory_used_mb" and decision.decision_class == "memory-leak":
        decision.leaf = "fault"
        return decision
    return None
