export type Verdict = "SUPPRESS" | "ALERT";

export interface KpiSpec {
  id: string;
  display_name: string;
  unit: string;
  baseline: number;
}

export interface ExpectedImpact {
  kpi: string;
  mode: "multiplier";
  low: number;
  high: number;
}

export interface ScenarioEvent {
  kind: string;
  id: string;
  start: string;
  end: string;
  expected_impacts: ExpectedImpact[];
  kickoff?: string;
  full_time?: string;
  pre_ramp_start?: string;
}

export interface ScenarioSummary {
  name: string;
  sim_start: string;
  sim_end: string;
  tick_seconds: number;
  kpis: KpiSpec[];
  events: ScenarioEvent[];
}

export interface Tick {
  ts: string;
  kpis: Record<string, number>;
  active_events: string[];
}

export interface Decision {
  ts: string;
  verdict: Verdict;
  class: "expected-event-traffic" | "unexplained-deviation";
  reason: string;
  confidence: number;
  evidence: {
    kpi: string;
    observed: number;
    baseline: number;
    ratio: number;
    active_events: string[];
    declared_range: {
      event_id: string;
      low: number;
      high: number;
    } | null;
  };
}

export type ReplayStatus = {
  type: "status";
  running: boolean;
  index: number;
  speed: number;
  ended: boolean;
};

export type ReplayMessage =
  | { type: "hello"; scenario: ScenarioSummary }
  | ReplayStatus
  | { type: "tick"; tick: Tick; decisions: Decision[] }
  | { type: "end" };
