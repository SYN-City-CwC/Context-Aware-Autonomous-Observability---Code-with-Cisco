from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class KpiSpec(BaseModel):
    id: str
    display_name: str
    unit: str
    baseline: float


class ExpectedImpact(BaseModel):
    kpi: str
    mode: Literal["multiplier"]
    low: float
    high: float


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


class AttackSpec(BaseModel):
    kind: str
    id: str
    start: datetime
    end: datetime
    target_kpi: str
    multiplier: AttackMultiplier
    additive_impacts: list[AdditiveImpact] = Field(default_factory=list)


class Scenario(BaseModel):
    name: str
    seed: int
    sim_start: datetime
    sim_end: datetime
    tick_seconds: int
    kpis: list[KpiSpec]
    events: list[EventSpec]
    attacks: list[AttackSpec] = Field(default_factory=list)
    faults: list[dict] = Field(default_factory=list)

    @property
    def baselines(self) -> dict[str, float]:
        return {kpi.id: kpi.baseline for kpi in self.kpis}


class Tick(BaseModel):
    ts: datetime
    kpis: dict[str, float]
    active_events: list[str]
    truth: list[str] = Field(default_factory=list)


class DetectorTick(BaseModel):
    ts: datetime
    kpis: dict[str, float]
    active_events: list[str]


class DeclaredRange(BaseModel):
    event_id: str
    low: float
    high: float


class Evidence(BaseModel):
    kpi: str
    observed: float
    baseline: float
    ratio: float
    active_events: list[str]
    declared_range: DeclaredRange | None = None


class Decision(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    ts: datetime
    verdict: Literal["SUPPRESS", "ALERT"]
    decision_class: Literal["expected-event-traffic", "unexplained-deviation"] = Field(
        alias="class"
    )
    reason: str
    confidence: float
    evidence: Evidence


class Timeline(BaseModel):
    scenario: str
    ticks: list[Tick]
    decisions: list[Decision]
