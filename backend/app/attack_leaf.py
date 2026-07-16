from __future__ import annotations

from app.models import Decision, Scenario, Tick


WEIGHTS = {"entropy": 0.25, "flow": 0.2, "iat": 0.2, "failure": 0.25, "coherence": 0.1}


def classify_attack(decision: Decision, tick: Tick, scenario: Scenario) -> Decision | None:
    values = tick.kpis
    entropy, flow, iat, failures = (values["login_source_entropy"], values["login_flow_correlation"], values["login_iat_cv"], values["auth_failure_ratio"])
    if decision.evidence.kpi == "auth_login_rps" and entropy < 0.55 and failures > 0.45:
        score = WEIGHTS["entropy"] * (1 - entropy) + WEIGHTS["flow"] * flow + WEIGHTS["iat"] * (1 - iat) + WEIGHTS["failure"] * failures + WEIGHTS["coherence"] * values["conversion_coherence"]
        decision.decision_class = "credential-stuffing"
        decision.leaf = "attack"
        decision.confidence = round(min(0.97, 0.5 + 0.45 * score), 3)
        decision.reason = f"source entropy {entropy:.2f} vs baseline {scenario.baselines['login_source_entropy']:.2f}; flow correlation {flow:.2f}; IAT CV {iat:.2f} (machine-regular); auth failures {failures:.0%}; watch-time coherent with match - verdict: credential stuffing overlaid on a real crowd."
        return decision
    if decision.evidence.kpi in {"tcp_half_open", "copp_drops"}:
        decision.decision_class = "volumetric-attack"
        decision.leaf = "attack"
        decision.reason = f"tcp half-open {values['tcp_half_open']:.0f} vs baseline {scenario.baselines['tcp_half_open']:.0f}; CoPP drops {values['copp_drops']:.0f}/min vs baseline {scenario.baselines['copp_drops']:.0f}; population stats remain human - verdict: volumetric attack, observe-only gate."
        return decision
    return None
