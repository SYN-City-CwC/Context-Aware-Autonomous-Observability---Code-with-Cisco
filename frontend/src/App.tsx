import { useEffect, useMemo, useRef, useState } from "react";
import {
  Area,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ActionRecord, Decision, KpiSpec, RcaRecord, ReplayStatus, ScenarioSummary, Tick, Verdict } from "./types";
import { ReplaySocket, backendHttpUrl } from "./ws";

const SPEEDS = [30, 60, 120, 300];
const HIGHLIGHT_MS = 2000;
const WINDOW_SECONDS = 45 * 60;

type ConnectionState = "connected" | "disconnected" | "ended";

type Highlight = {
  verdict: Verdict;
  token: number;
};

type ChartPoint = {
  ts: string;
  value: number;
  p10: number | null;
  band: number | null;
  ghost: number | null;
};

export default function App() {
  const [scenario, setScenario] = useState<ScenarioSummary | null>(null);
  const [ticks, setTicks] = useState<Tick[]>([]);
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [actions, setActions] = useState<ActionRecord[]>([]);
  const [rcaRecords, setRcaRecords] = useState<RcaRecord[]>([]);
  const [status, setStatus] = useState<ReplayStatus | null>(null);
  const [connection, setConnection] = useState<ConnectionState>("disconnected");
  const [speed, setSpeed] = useState(60);
  const [highlights, setHighlights] = useState<Record<string, Highlight>>({});
  const [hasStarted, setHasStarted] = useState(false);
  const socketRef = useRef<ReplaySocket | null>(null);
  const pendingRestartRef = useRef(false);
  const speedRef = useRef(speed);

  useEffect(() => {
    speedRef.current = speed;
  }, [speed]);

  useEffect(() => {
    const socket = new ReplaySocket({
      onOpen: () => {
        setConnection("connected");
        if (pendingRestartRef.current) {
          pendingRestartRef.current = false;
          socketRef.current?.send({ cmd: "start", speed: speedRef.current });
        }
      },
      onClose: () => {
        setConnection((current) => (current === "ended" ? "ended" : "disconnected"));
        setStatus((current) => current ? { ...current, running: false } : current);
      },
      onError: () => setConnection("disconnected"),
      onMessage: (message) => {
        if (message.type === "hello") {
          setScenario(message.scenario);
        }
        if (message.type === "status") {
          setStatus(message);
        }
        if (message.type === "tick") {
          setTicks((current) => [...current, message.tick]);
          if (message.decisions.length > 0) {
            setDecisions((current) => [...message.decisions, ...current]);
            flashDecisionKpis(message.decisions);
          }
          if (message.actions.length > 0) {
            setActions((current) => [...message.actions, ...current]);
          }
        }
        if (message.type === "end") {
          setConnection("ended");
          setStatus((current) => current ? { ...current, running: false, ended: true } : current);
        }
      },
    });
    socketRef.current = socket;
    socket.connect();
    return () => socket.close();
  }, []);

  useEffect(() => {
    fetch(`${backendHttpUrl()}/api/rca`)
      .then((response) => response.json() as Promise<RcaRecord[]>)
      .then(setRcaRecords)
      .catch(() => setRcaRecords([]));
  }, []);

  const latestTick = ticks[ticks.length - 1] ?? null;
  const suppressions = decisions.filter((decision) => decision.verdict === "SUPPRESS").length;
  const alerts = decisions.filter((decision) => decision.verdict === "ALERT").length;
  const isRunning = status?.running ?? false;

  function flashDecisionKpis(newDecisions: Decision[]) {
    const now = Date.now();
    setHighlights((current) => {
      const next = { ...current };
      for (const decision of newDecisions) {
        next[decision.evidence.kpi] = { verdict: decision.verdict, token: now };
      }
      return next;
    });
    window.setTimeout(() => {
      setHighlights((current) => {
        const next = { ...current };
        for (const decision of newDecisions) {
          if (next[decision.evidence.kpi]?.token === now) {
            delete next[decision.evidence.kpi];
          }
        }
        return next;
      });
    }, HIGHLIGHT_MS);
  }

  function play() {
    if (!socketRef.current?.isOpen()) {
      return;
    }
    if (!hasStarted || status?.ended) {
      setHasStarted(true);
      setTicks([]);
      setDecisions([]);
      setActions([]);
      setHighlights({});
      setConnection("connected");
      socketRef.current.send({ cmd: "start", speed });
      return;
    }
    socketRef.current.send({ cmd: "resume" });
  }

  function pause() {
    socketRef.current?.send({ cmd: "pause" });
  }

  function restart() {
    setHasStarted(true);
    setTicks([]);
    setDecisions([]);
    setActions([]);
    setHighlights({});
    if (!socketRef.current?.isOpen() || status?.ended) {
      pendingRestartRef.current = true;
      socketRef.current?.connect();
      return;
    }
    socketRef.current.send({ cmd: "restart" });
    socketRef.current.send({ cmd: "speed", value: speed });
  }

  function reconnect() {
    setHasStarted(false);
    setTicks([]);
    setDecisions([]);
    setActions([]);
    setHighlights({});
    setStatus(null);
    setConnection("disconnected");
    socketRef.current?.connect();
  }

  function updateSpeed(value: number) {
    setSpeed(value);
    socketRef.current?.send({ cmd: "speed", value });
  }

  function narrateAll() {
    fetch(`${backendHttpUrl()}/api/rca?narrate=1`).then((response) => response.json() as Promise<RcaRecord[]>).then(setRcaRecords);
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">SYN-City Stage 3 sprint</p>
          <h1>{scenario?.name ?? "connecting"}</h1>
        </div>
        <div className="clock-block">
          <span className="label">Sim clock</span>
          <strong>{latestTick ? formatTime(latestTick.ts) : "--:--:--"}</strong>
        </div>
        <div className="controls" aria-label="Replay controls">
          <button onClick={play} disabled={connection !== "connected" || isRunning}>
            Play
          </button>
          <button onClick={pause} disabled={!isRunning}>
            Pause
          </button>
          <button onClick={restart} disabled={connection === "disconnected"}>
            Restart
          </button>
          <label>
            <span>Speed</span>
            <select value={speed} onChange={(event) => updateSpeed(Number(event.target.value))}>
              {SPEEDS.map((value) => (
                <option key={value} value={value}>
                  {value}x
                </option>
              ))}
            </select>
          </label>
          <ConnectionBadge state={connection} />
          {connection === "disconnected" ? <button onClick={reconnect}>Reconnect</button> : null}
        </div>
      </header>

      <main className="dashboard">
        <section className="kpi-pane" aria-label="KPI strips">
          {(scenario?.kpis ?? []).filter((kpi) => kpi.layer !== "deep" && kpi.layer !== "population").map((kpi) => (
            <KpiStrip
              key={kpi.id}
              kpi={kpi}
              ticks={ticks}
              tickSeconds={scenario?.tick_seconds ?? 10}
              highlight={highlights[kpi.id]}
            />
          ))}
          <h2 className="deep-heading">Population telemetry</h2>
          {(scenario?.kpis ?? []).filter((kpi) => kpi.layer === "population").map((kpi) => (
            <KpiStrip key={kpi.id} kpi={kpi} ticks={ticks} tickSeconds={scenario?.tick_seconds ?? 10} highlight={highlights[kpi.id]} />
          ))}
          <h2 className="deep-heading">Deep telemetry</h2>
          {(scenario?.kpis ?? []).filter((kpi) => kpi.layer === "deep").map((kpi) => (
            <KpiStrip key={kpi.id} kpi={kpi} ticks={ticks} tickSeconds={scenario?.tick_seconds ?? 10} highlight={highlights[kpi.id]} />
          ))}
        </section>

        <section className="decision-pane" aria-label="Decision feed">
          <div className="feed-header">
            <div>
              <p className="eyebrow">Decision feed</p>
              <h2>Suppression and alert log</h2>
            </div>
            <span className="feed-counts">{suppressions} suppressions / {alerts} alerts / {actions.length} actions</span>
          </div>
          <div className="decision-list">
            {decisions.length === 0 ? (
              <p className="empty-state">No decisions yet.</p>
            ) : (
              decisions.map((decision, index) => (
                <DecisionCard key={`${decision.ts}-${decision.evidence.kpi}-${index}`} decision={decision} />
              ))
            )}
            {actions.map((action) => <ActionCard key={action.id} action={action} />)}
            <section className="rca-list" aria-label="RCA reports">
              <div className="feed-header"><p className="eyebrow">RCA reports</p><button onClick={narrateAll}>Narrate all</button></div>
              {rcaRecords.map((record) => <RcaCard key={record.incident_id} record={record} />)}
            </section>
          </div>
        </section>
      </main>

      <footer className="backend-line">Backend: {backendHttpUrl()}</footer>
    </div>
  );
}

function KpiStrip({
  kpi,
  ticks,
  tickSeconds,
  highlight,
}: {
  kpi: KpiSpec;
  ticks: Tick[];
  tickSeconds: number;
  highlight?: Highlight;
}) {
  const current = ticks[ticks.length - 1]?.kpis[kpi.id] ?? kpi.baseline;
  const windowSize = Math.max(1, Math.ceil(WINDOW_SECONDS / tickSeconds));
  const data = useMemo<ChartPoint[]>(
    () =>
      ticks.slice(-windowSize).map((tick) => ({
        ts: formatTime(tick.ts),
        value: tick.kpis[kpi.id],
        p10: tick.envelope?.[kpi.id]?.p10 ?? null,
        band: tick.envelope?.[kpi.id]
          ? tick.envelope[kpi.id].p90 - tick.envelope[kpi.id].p10
          : null,
        ghost: tick.ghost_kpis?.[kpi.id] ?? null,
      })),
    [kpi.id, ticks, windowSize],
  );
  const highlightClass = highlight ? `flash-${highlight.verdict.toLowerCase()}` : "";

  return (
    <article className={`kpi-strip ${highlightClass}`}>
      <div className="kpi-meta">
        <div>
          <h3>{kpi.display_name}</h3>
          <span>{kpi.id}</span>
        </div>
        <strong>{formatKpiValue(current, kpi.unit)}</strong>
      </div>
      <div className="chart-wrap">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data}>
            <XAxis dataKey="ts" hide />
            <YAxis hide domain={["dataMin", "dataMax"]} />
            <Tooltip
              contentStyle={{ background: "#111827", border: "1px solid #263241", color: "#e5edf5" }}
              formatter={(value, name) => [
                formatKpiValue(Number(value), kpi.unit),
                name === "value" ? kpi.display_name : "expected envelope",
              ]}
              labelFormatter={(value) => `Sim ${value}`}
            />
            <Area
              type="monotone"
              dataKey="p10"
              stackId="envelope"
              stroke="none"
              fill="transparent"
              isAnimationActive={false}
            />
            <Area
              type="monotone"
              dataKey="band"
              stackId="envelope"
              stroke="none"
              fill="#34506d"
              fillOpacity={0.32}
              connectNulls
              isAnimationActive={false}
            />
            <Line type="monotone" dataKey="ghost" stroke="#6b7280" strokeDasharray="4 4" dot={false} strokeWidth={1} isAnimationActive={false} />
            <Line type="monotone" dataKey="value" stroke="#89b4fa" dot={false} strokeWidth={2} isAnimationActive={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </article>
  );
}

function ActionCard({ action }: { action: ActionRecord }) {
  return <article className="decision-card action"><div className="decision-topline"><time>{formatTime(action.ts)}</time><span className="verdict action">ACTION</span></div><div className="decision-main"><strong>{action.action}</strong><span>{action.target_kpi}</span><span>{action.mttr_seconds === null ? "verifying" : `${action.mttr_seconds}s MTTR`}</span></div><p>Approved edge rate limit reduced the credential-stuffing overlay by 80%.</p></article>;
}

function RcaCard({ record }: { record: RcaRecord }) {
  return <article className="decision-card rca"><div className="decision-main"><strong>{record.root_cause_class}</strong><span>{Math.round(record.confidence * 100)}% confidence</span>{record.narrative_provider ? <span className="verdict action">{record.narrative_provider}</span> : null}</div><p>{record.narrative ?? record.evidence_chain[record.evidence_chain.length - 1]}</p></article>;
}

function DecisionCard({ decision }: { decision: Decision }) {
  return (
    <article className={`decision-card ${decision.verdict.toLowerCase()}`}>
      <div className="decision-topline">
        <time>{formatTime(decision.ts)}</time>
        <span className={`verdict ${decision.verdict.toLowerCase()}`}>{decision.verdict}</span>
      </div>
      <div className="decision-main">
        <strong>{decision.evidence.kpi}</strong>
        <span>{decision.class}</span>
        {decision.leaf ? <span>{decision.leaf} leaf</span> : null}
        <span>{decision.evidence.ratio.toFixed(1)}x expected</span>
        <span>{Math.round(decision.confidence * 100)}% confidence</span>
      </div>
      <p>{decision.reason}</p>
    </article>
  );
}

function ConnectionBadge({ state }: { state: ConnectionState }) {
  const label = state === "ended" ? "REPLAY ENDED" : state;
  return <span className={`connection-badge ${state}`}>{label}</span>;
}

function formatTime(value: string): string {
  const date = new Date(value);
  return date.toLocaleTimeString("en-US", {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZone: "UTC",
  });
}

function formatKpiValue(value: number, unit: string): string {
  if (unit === "ratio") {
    return `${(value * 100).toFixed(2)}%`;
  }
  if (unit === "ms") {
    return `${Math.round(value)} ms`;
  }
  if (unit === "rps") {
    return `${Math.round(value).toLocaleString()} rps`;
  }
  return `${Math.round(value).toLocaleString()} ${unit}`;
}
