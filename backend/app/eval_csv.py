from __future__ import annotations

from collections import Counter
from pathlib import Path

from app.csv_loader import load_csv_ticks
from app.envelope import run_envelope_detector
from app.models import Tick
from app.scenario import load_scenario


CSV_PATH = Path(__file__).resolve().parents[1] / "data" / "context_aware_observability_sample_5000_v2.csv"


def main() -> None:
    scenario = load_scenario()
    ticks, covered = load_csv_ticks(CSV_PATH, scenario)
    padded = [Tick(ts=tick.ts, kpis={**scenario.baselines, **tick.kpis}, active_events=[], truth=[]) for tick in ticks]
    _, decisions = run_envelope_detector(scenario, padded)
    alerts = [decision for decision in decisions if decision.verdict == "ALERT"]
    counts = Counter(decision.evidence.kpi for decision in alerts)
    lines = [f"rows evaluated: {len(ticks)}", f"coverage: {', '.join(covered)}", "Tier-2 omitted: AE expects memory_used_mb, absent from CSV; envelope + silence-compatible benchmark only.", f"alerts raised: {len(alerts)} ({dict(counts)})", f"false-positive rate: {len(alerts) / len(ticks):.4%}", "first 5 alert reasons:", *[decision.reason for decision in alerts[:5]]]
    report = "\n".join(lines) + "\n"
    print(report, end="")
    (CSV_PATH.parent / "csv_benchmark.md").write_text(report, encoding="utf-8")


if __name__ == "__main__":
    main()
