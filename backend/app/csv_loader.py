"""Load the external normal-traffic CSV.

Volume, latency, and count columns are median-normalized to scenario baselines so the
existing model scale applies. Scale-free ratio-like columns are passed through unchanged.
Only the TASK-08 mapping table is represented here; unlisted source columns are ignored.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.models import Scenario, Tick


COLUMN_MAP = {
    "active_users": "streaming_concurrents", "http_rps": "edge_rps", "checkout_rps": "checkout_rps", "login_rps": "auth_login_rps", "latency_p99_ms": "p99_latency_ms", "http_5xx_rate_pct": "error_rate_5xx", "syn_half_open_count": "tcp_half_open", "bgp_updates_total": "bgp_update_rate", "copp_drops": "copp_drops", "syslog_template_rate": "syslog_rate", "telemetry_queue_depth": "agent_queue_depth", "source_ip_entropy": "login_source_entropy", "flow_correlation": "login_flow_correlation", "interarrival_cv": "login_iat_cv", "login_fail_rate_pct": "auth_failure_ratio", "watch_time_index": "watch_time_index", "checkout_success_rate_pct": "conversion_coherence", "retry_amplification": "retry_amplification",
}
PERCENT_COLUMNS = {"http_5xx_rate_pct", "login_fail_rate_pct", "checkout_success_rate_pct"}
SCALE_FREE = {"error_rate_5xx", "login_source_entropy", "login_flow_correlation", "login_iat_cv", "auth_failure_ratio", "watch_time_index", "conversion_coherence", "retry_amplification"}


def load_csv_ticks(path: str | Path, scenario: Scenario) -> tuple[list[Tick], list[str]]:
    frame = pd.read_csv(path)
    covered = [target for source, target in COLUMN_MAP.items() if source in frame.columns]
    values: dict[str, pd.Series] = {}
    for source, target in COLUMN_MAP.items():
        if source not in frame.columns:
            continue
        series = frame[source].astype(float)
        if source in PERCENT_COLUMNS:
            series = series / 100.0
        if target not in SCALE_FREE:
            series = series * scenario.baselines[target] / max(float(series.median()), 1e-9)
        values[target] = series
    timestamps = pd.to_datetime(frame["timestamp"], utc=True)
    return [Tick(ts=ts.to_pydatetime(), kpis={name: float(series.iloc[index]) for name, series in values.items()}, active_events=[], truth=[]) for index, ts in enumerate(timestamps)], covered
