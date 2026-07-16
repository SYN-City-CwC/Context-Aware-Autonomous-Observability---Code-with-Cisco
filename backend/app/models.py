from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class KpiSpec(BaseModel):
    id: str
    display_name: str
    unit: str
    baseline: float
    diurnal: float = 0.0
    layer: Literal["core", "deep", "population"] = "core"


class ExpectedImpact(BaseModel):
    kpi: str
    mode: Literal["multiplier"]
    low: float
    high: float


class GoalImpact(BaseModel):
    kpi: str
    low: float
    high: float
    decay_seconds_low: float
    decay_seconds_high: float


class AttackMultiplier(BaseModel):
    low: float
    high: float


class AdditiveImpact(BaseModel):
    kpi: str
    value: float


class EventSpec(BaseModel):
    kind: Literal["match", "campaign"]
    id: str
    start: datetime
    end: datetime
    expected_impacts: list[ExpectedImpact]
    kickoff: datetime | None = None
    full_time: datetime | None = None
    pre_ramp_start: datetime | None = None
    goals: list[datetime] = Field(default_factory=list)
    goal_impact: GoalImpact | None = None


class PriorEventSpec(BaseModel):
    kind: Literal["match", "campaign"]
    id: str
    day_offset: int
    start: str
    end: str
    expected_impacts: list[ExpectedImpact]
    kickoff: str | None = None
    full_time: str | None = None
    pre_ramp_start: str | None = None
    goals: list[str] = Field(default_factory=list)
    goal_impact: GoalImpact | None = None


class HistorySpec(BaseModel):
    days: int
    prior_events: list[PriorEventSpec] = Field(default_factory=list)


class AttackSpec(BaseModel):
    kind: str
    id: str
    start: datetime
    end: datetime
    target_kpi: str
    multiplier: AttackMultiplier
    additive_impacts: list[AdditiveImpact] = Field(default_factory=list)
    population_profile: dict[str, float] = Field(default_factory=dict)


class MemoryLeakFault(BaseModel):
    kind: Literal["memory_leak"]
    id: str
    kpi: str
    start: datetime
    end: datetime
    slope_mb_per_min: float


class TelemetrySilenceFault(BaseModel):
    kind: Literal["telemetry_silence"]
    id: str
    kpi: str
    start: datetime
    end: datetime


FaultSpec = AttackSpec | MemoryLeakFault | TelemetrySilenceFault


class RetryStormFault(BaseModel):
    kind: Literal["retry_storm"]
    id: str
    path: list[str]
    start: datetime
    end: datetime
    amplification: float


class DeploymentChange(BaseModel):
    file: str
    line: int
    key: str
    old: float
    new: float


class Deployment(BaseModel):
    service: str
    version: str
    ts: datetime
    change: DeploymentChange
    note: str


class Scenario(BaseModel):
    name: str
    seed: int
    sim_start: datetime
    sim_end: datetime
    tick_seconds: int
    kpis: list[KpiSpec]
    events: list[EventSpec]
    history: HistorySpec | None = None
    attacks: list[AttackSpec] = Field(default_factory=list)
    faults: list[FaultSpec | RetryStormFault] = Field(default_factory=list)
    deployments: list[Deployment] = Field(default_factory=list)

    @property
    def baselines(self) -> dict[str, float]:
        return {kpi.id: kpi.baseline for kpi in self.kpis}


class Tick(BaseModel):
    ts: datetime
    kpis: dict[str, float]
    active_events: list[str]
    truth: list[str] = Field(default_factory=list)
    envelope: dict[str, "EnvelopeBand"] | None = None
    ghost_kpis: dict[str, float] | None = None


class DetectorTick(BaseModel):
    ts: datetime
    kpis: dict[str, float]
    active_events: list[str]


class DeclaredRange(BaseModel):
    event_id: str
    low: float
    high: float


class EnvelopeBand(BaseModel):
    p10: float
    p90: float


class Evidence(BaseModel):
    kpi: str
    observed: float
    baseline: float
    ratio: float
    active_events: list[str]
    declared_range: DeclaredRange | None = None
    p10: float | None = None
    p50: float | None = None
    p90: float | None = None
    context_blind_p90: float | None = None


class Decision(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    ts: datetime
    verdict: Literal["SUPPRESS", "ALERT"]
    decision_class: Literal[
        "expected-event-traffic", "unexplained-deviation", "unexplained-drop",
        "structural-anomaly", "memory-leak", "telemetry-silence", "volumetric-attack",
        "credential-stuffing", "retry-storm"
    ] = Field(alias="class")
    reason: str
    confidence: float
    evidence: Evidence
    leaf: Literal["attack", "fault"] | None = None


class ActionSpec(BaseModel):
    id: str
    kind: Literal["observe", "edge_rate_limit", "circuit_break", "config_rollback"]
    tier: Literal[0, 1, 2]
    blast_radius: float
    description: str
    inverse_description: str


class GateResult(BaseModel):
    verdict: Literal["APPROVED", "NEEDS_REVIEW", "BLOCKED"]
    reason: str


class ActionTransition(BaseModel):
    state: str
    ts: datetime


class AuditEntry(BaseModel):
    ts: datetime
    kind: Literal["decision", "gate", "rollout", "probe", "hitl", "revert"]
    detail: str
    action_id: str | None = None
    decision_ts: datetime | None = None


class ActionRecord(BaseModel):
    id: str
    ts: datetime
    action: Literal["observe", "edge_rate_limit", "circuit_break", "config_rollback"]
    target_kpi: str
    trigger_decision_ts: datetime
    approved: bool
    mttr_seconds: int | None = None
    spec_id: str
    tier: Literal[0, 1, 2]
    state: str
    transitions: list[ActionTransition] = Field(default_factory=list)
    gate_reason: str
    trigger_reason: str
    probes: dict[str, float] = Field(default_factory=dict)
    rollback: str | None = None


class RcaRecord(BaseModel):
    incident_id: str
    symptom_storm: list[str]
    root_cause_class: str
    evidence_chain: list[str]
    confidence: float
    actions_taken: list[str]
    mttr_seconds: int | None = None
    narrative: str | None = None
    narrative_provider: Literal["groq", "gemini", "rules"] | None = None


class Timeline(BaseModel):
    scenario: str
    ticks: list[Tick]
    decisions: list[Decision]
    actions: list[ActionRecord] = Field(default_factory=list)
    rca_records: list[RcaRecord] = Field(default_factory=list)
    audit_log: list[AuditEntry] = Field(default_factory=list)
