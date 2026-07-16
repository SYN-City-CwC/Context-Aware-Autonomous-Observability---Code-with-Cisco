from __future__ import annotations

from app.models import ActionRecord, Decision, RcaRecord


def build_rca_records(decisions: list[Decision], actions: list[ActionRecord]) -> list[RcaRecord]:
    records: list[RcaRecord] = []
    for decision in decisions:
        kpi = decision.evidence.kpi
        if decision.decision_class == "retry-storm":
            records.append(RcaRecord(incident_id="checkout-retry-storm", symptom_storm=["retry_amplification", "p99_latency_ms", "error_rate_5xx"], root_cause_class="retry-storm", evidence_chain=[decision.reason, _retry_fix(decision, decisions)], confidence=decision.confidence, actions_taken=[]))
        elif decision.decision_class == "credential-stuffing":
            action = next((item for item in actions if item.trigger_decision_ts == decision.ts), None)
            records.append(RcaRecord(incident_id="credential-stuffing-CS-01", symptom_storm=["auth_login_rps", "auth_failure_ratio"], root_cause_class="credential-stuffing", evidence_chain=[decision.reason], confidence=decision.confidence, actions_taken=[action.id] if action else [], mttr_seconds=action.mttr_seconds if action else None))
        elif kpi in {"tcp_half_open", "copp_drops"}:
            records.append(RcaRecord(incident_id="syn-flood-SYN-01", symptom_storm=["tcp_half_open", "copp_drops"], root_cause_class="volumetric-attack", evidence_chain=[decision.reason], confidence=decision.confidence, actions_taken=[]))
        elif decision.verdict == "SUPPRESS":
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
        elif decision.decision_class == "volumetric-attack":
            records.append(RcaRecord(incident_id="syn-flood-SYN-01", symptom_storm=["tcp_half_open", "copp_drops"], root_cause_class="volumetric-attack", evidence_chain=[decision.reason], confidence=decision.confidence, actions_taken=[]))
        elif decision.decision_class == "memory-leak":
            records.append(RcaRecord(incident_id="memory-leak-LEAK-01", symptom_storm=["memory_used_mb"], root_cause_class="internal-fault", evidence_chain=[decision.reason, "Memory growth is independent of traffic volume."], confidence=decision.confidence, actions_taken=[]))
        elif decision.decision_class == "telemetry-silence":
            records.append(RcaRecord(incident_id="telemetry-silence-SIL-01", symptom_storm=["bgp_update_rate"], root_cause_class="operational-fault", evidence_chain=[decision.reason], confidence=decision.confidence, actions_taken=[]))
    deduped: dict[str, RcaRecord] = {}
    for record in records:
        existing = deduped.get(record.incident_id)
        if existing is None:
            deduped[record.incident_id] = record
        else:
            existing.evidence_chain.extend(item for item in record.evidence_chain if item not in existing.evidence_chain)
            existing.confidence = max(existing.confidence, record.confidence)
    return list(deduped.values())


def _retry_fix(decision: Decision, decisions: list[Decision]) -> str:
    return "Proposed fix: revert checkout-svc v2.31 retry.go:42 timeout_ms 200->2000; cap retries, add exponential backoff and a circuit breaker."
