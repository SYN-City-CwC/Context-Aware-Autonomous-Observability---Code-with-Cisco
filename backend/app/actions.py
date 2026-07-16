from __future__ import annotations

from app.models import ActionRecord, Decision


def maybe_act(decision: Decision) -> ActionRecord | None:
    if (
        decision.verdict != "ALERT"
        or decision.decision_class != "credential-stuffing"
        or decision.confidence < 0.8
    ):
        return None
    return ActionRecord(
        id=f"edge-rate-limit-{decision.ts.strftime('%H%M%S')}",
        ts=decision.ts,
        action="edge_rate_limit",
        target_kpi="auth_login_rps",
        trigger_decision_ts=decision.ts,
        approved=True,
    )
