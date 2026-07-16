from __future__ import annotations

from app.scenario import load_scenario
from app.timeline import build_timeline


def main() -> None:
    scenario = load_scenario()
    timeline = build_timeline(scenario)
    suppressions = 0
    alerts = 0
    for decision in timeline.decisions:
        if decision.verdict == "SUPPRESS":
            suppressions += 1
        else:
            alerts += 1
        print(
            f"{decision.ts.strftime('%H:%M:%S')} {decision.verdict} "
            f"{decision.evidence.kpi} ratio={decision.evidence.ratio:.1f} "
            f"confidence={decision.confidence:.2f} {decision.reason}"
        )
    print(
        f"Summary: total ticks={len(timeline.ticks)}, "
        f"suppressions={suppressions}, alerts={alerts}"
    )


if __name__ == "__main__":
    main()
