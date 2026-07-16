from app.models import ActionSpec

ACTION_CATALOG = {
    "observe": ActionSpec(id="observe", kind="observe", tier=0, blast_radius=0.0, description="observe volumetric incident", inverse_description="none"),
    "edge_rate_limit": ActionSpec(id="edge_rate_limit", kind="edge_rate_limit", tier=0, blast_radius=0.1, description="rate limit auth cohort", inverse_description="lift rate limit"),
    "circuit_break": ActionSpec(id="circuit_break", kind="circuit_break", tier=1, blast_radius=0.2, description="open checkout circuit", inverse_description="close circuit"),
    "config_rollback": ActionSpec(id="config_rollback", kind="config_rollback", tier=2, blast_radius=0.25, description="apply canaried timeout fix", inverse_description="restore prior config"),
}
