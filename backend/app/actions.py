from app.action_catalog import ACTION_CATALOG
from app.models import ActionRecord, AuditEntry, Decision, GateResult


def policy_gate(tier: int, confidence: float, blast_radius: float) -> GateResult:
    if tier == 2: return GateResult(verdict="NEEDS_REVIEW", reason="human approval is mandatory for tier 2")
    if confidence < 0.6: return GateResult(verdict="BLOCKED", reason=f"confidence {confidence:.2f} is below 0.60")
    if confidence >= 0.8 and blast_radius <= 0.3: return GateResult(verdict="APPROVED", reason=f"confidence {confidence:.2f}, blast radius {blast_radius:.2f}")
    return GateResult(verdict="NEEDS_REVIEW", reason=f"confidence {confidence:.2f}, blast radius {blast_radius:.2f}")


def action_for(decision: Decision, spec_id: str) -> tuple[ActionRecord, AuditEntry]:
    spec = ACTION_CATALOG[spec_id]; gate = policy_gate(spec.tier, decision.confidence, spec.blast_radius)
    record = ActionRecord(id=f"{spec_id}-{decision.ts.strftime('%H%M%S')}", ts=decision.ts, action=spec.kind, target_kpi=decision.evidence.kpi, trigger_decision_ts=decision.ts, approved=gate.verdict == "APPROVED", spec_id=spec.id, tier=spec.tier, state=gate.verdict, transitions=[{"state":"PROPOSED","ts":decision.ts},{"state":gate.verdict,"ts":decision.ts}], gate_reason=gate.reason, trigger_reason=decision.reason)
    return record, AuditEntry(ts=decision.ts, kind="gate", detail=gate.reason, action_id=record.id, decision_ts=decision.ts)


def maybe_act(decision: Decision) -> ActionRecord | None:
    if decision.decision_class != "credential-stuffing" or decision.verdict != "ALERT": return None
    return action_for(decision, "edge_rate_limit")[0]
