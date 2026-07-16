rows evaluated: 5000
coverage: streaming_concurrents, edge_rps, checkout_rps, auth_login_rps, p99_latency_ms, error_rate_5xx, tcp_half_open, bgp_update_rate, copp_drops, syslog_rate, agent_queue_depth, login_source_entropy, login_flow_correlation, login_iat_cv, auth_failure_ratio, watch_time_index, conversion_coherence, retry_amplification
Tier-2 omitted: AE expects memory_used_mb, absent from CSV; envelope + silence-compatible benchmark only.
alerts raised: 350 ({'streaming_concurrents': 34, 'edge_rps': 18, 'checkout_rps': 27, 'auth_login_rps': 33, 'p99_latency_ms': 43, 'error_rate_5xx': 5, 'bgp_update_rate': 1, 'copp_drops': 1, 'tcp_half_open': 3, 'syslog_rate': 5, 'agent_queue_depth': 12, 'auth_failure_ratio': 114, 'watch_time_index': 1, 'login_flow_correlation': 51, 'login_iat_cv': 2})
false-positive rate: 7.0000%
first 5 alert reasons:
streaming_concurrents observed 1455991.52 outside band [2306603.98, 2602235.01]; no declared context is active; no declared context explains it
edge_rps observed 86229.16 outside band [140016.85, 157754.71]; no declared context is active; no declared context explains it
checkout_rps observed 642.67 outside band [1052.57, 1185.60]; no declared context is active; no declared context explains it
auth_login_rps observed 1146.42 outside band [1753.07, 1974.79]; no declared context is active; no declared context explains it
p99_latency_ms observed 155.31 outside band [187.08, 210.68]; no declared context is active; no declared context explains it
