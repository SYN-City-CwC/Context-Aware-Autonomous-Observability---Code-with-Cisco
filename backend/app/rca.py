from __future__ import annotations

from app.models import ActionRecord, Decision, RcaRecord


def build_rca_records(decisions: list[Decision], actions: list[ActionRecord]) -> list[RcaRecord]:
    records: list[RcaRecord] = []
    for decision in decisions:
        kpi = decision.evidence.kpi
        if decision.verdict == "SUPPRESS":
            records.append(
                RcaRecord(
                    incident_id=f"expected-{kpi}-{decision.ts.strftime('%H%M%S')}",
                    symptom_storm=[kpi],
                    root_cause_class="expected-event-traffic",
                    evidence_chain=[decision.reason],
                    confidence=decision.confidence,
                    actions_taken=[],
                )
            )
        elif kpi == "auth_login_rps":
            action = next((item for item in actions if item.trigger_decision_ts == decision.ts), None)
            records.append(
                RcaRecord(
                    incident_id="credential-stuffing-CS-01",
                    symptom_storm=["auth_login_rps", "p99_latency_ms", "error_rate_5xx"],
                    root_cause_class="credential-stuffing",
                    evidence_chain=[decision.reason, "Rate limit reduced the attack overlay by 80% in the simulator."],
                    confidence=decision.confidence,
                    actions_taken=[action.id] if action else [],
                    mttr_seconds=action.mttr_seconds if action else None,
                )
            )
        elif kpi in {"p99_latency_ms", "error_rate_5xx"}:
            records.append(
                RcaRecord(
                    incident_id="checkout-retry-storm",
                    symptom_storm=["p99_latency_ms", "error_rate_5xx"],
                    root_cause_class="internal-fault",
                    evidence_chain=[
                        decision.reason,
                        "checkout-svc v2.31 deployed 38 minutes earlier set request timeout to 200ms; retry amplification follows.",
                        "Proposed fix: checkout-svc/retry.go:42 - cap retries at 3, add exponential backoff and a circuit breaker; revert timeout to 2000ms pending root-cause fix.",
                        "Scripted demonstration of localization output format, not a live static-analysis engine.",
                    ],
                    confidence=decision.confidence,
                    actions_taken=[],
                )
            )
    return records
