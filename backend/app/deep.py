from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Any

import numpy as np
import torch
from sklearn.ensemble import IsolationForest

from app.models import Decision, Evidence, MemoryLeakFault, Scenario, Tick


WINDOW = 30


class LstmAutoencoder(torch.nn.Module):
    def __init__(self, channels: int) -> None:
        super().__init__()
        self.encoder = torch.nn.LSTM(channels, 16, batch_first=True)
        self.latent = torch.nn.Linear(16, 8)
        self.expand = torch.nn.Linear(8, 16)
        self.decoder = torch.nn.LSTM(16, channels, batch_first=True)

    def forward(self, values: torch.Tensor) -> torch.Tensor:
        encoded, _ = self.encoder(values)
        latent = self.latent(encoded[:, -1, :])
        repeated = self.expand(latent).unsqueeze(1).repeat(1, values.shape[1], 1)
        decoded, _ = self.decoder(repeated)
        return decoded


def train_deep_model(
    scenario: Scenario, ticks: list[Tick], train_indices: list[int], validation_indices: list[int], output_dir: Path
) -> dict[str, Any]:
    channels = [kpi.id for kpi in scenario.kpis if kpi.layer == "deep"]
    minute_ticks = [tick for tick in ticks if tick.ts.second == 0]
    train_dates = {ticks[index].ts.date() for index in train_indices}
    validation_dates = {ticks[index].ts.date() for index in validation_indices}
    train_rows = _matrix([tick for tick in minute_ticks if tick.ts.date() in train_dates], channels)
    val_rows = _matrix([tick for tick in minute_ticks if tick.ts.date() in validation_dates], channels)
    means, stds = train_rows.mean(axis=0), np.maximum(train_rows.std(axis=0), 1e-6)
    train_windows = _windows((train_rows - means) / stds)
    val_windows = _windows((val_rows - means) / stds)
    torch.manual_seed(scenario.seed)
    torch.use_deterministic_algorithms(True)
    torch.set_num_threads(1)
    model = LstmAutoencoder(len(channels))
    optimizer = torch.optim.Adam(model.parameters(), lr=0.01)
    values = torch.tensor(train_windows, dtype=torch.float32)
    for _ in range(8):
        optimizer.zero_grad()
        reconstruction = model(values)
        loss = torch.mean((reconstruction - values) ** 2)
        loss.backward()
        optimizer.step()
    train_errors = _errors(model, train_windows)
    val_errors = _errors(model, val_windows)
    forest = IsolationForest(random_state=scenario.seed, n_estimators=100, contamination="auto")
    forest.fit(train_errors)
    val_scores = -forest.score_samples(val_errors)
    threshold = float(np.percentile(val_scores, 99.5))
    np.savez(output_dir / "deep_iforest.npz", train_errors=train_errors, means=means, stds=stds, channels=np.array(channels), threshold=threshold)
    torch.save(model.state_dict(), output_dir / "deep_lstm.pt")
    return {"channels": channels, "means": means.tolist(), "stds": stds.tolist(), "threshold": threshold, "validation_score": {"p98": float(np.percentile(val_scores, 98)), "p995": threshold, "max": float(val_scores.max())}, "model": "torch-lstm-ae"}


def deep_decisions(scenario: Scenario, ticks: list[Tick], model_dir: Path) -> list[Decision]:
    artifact = np.load(model_dir / "deep_iforest.npz", allow_pickle=False)
    channels = artifact["channels"].tolist()
    means, stds = artifact["means"], artifact["stds"]
    threshold = float(artifact["threshold"])
    model = LstmAutoencoder(len(channels))
    model.load_state_dict(torch.load(model_dir / "deep_lstm.pt", map_location="cpu", weights_only=True))
    model.eval()
    forest = IsolationForest(random_state=scenario.seed, n_estimators=100)
    forest.fit(artifact["train_errors"])
    rows: deque[np.ndarray] = deque(maxlen=WINDOW)
    decisions: list[Decision] = []
    breaches = 0
    active = False
    for tick in ticks:
        if tick.ts.second != 0:
            continue
        rows.append((np.array([tick.kpis[channel] for channel in channels]) - means) / stds)
        if len(rows) < WINDOW:
            continue
        errors = _errors(model, np.array([rows]))[0]
        score = float(-forest.score_samples(np.array([errors]))[0])
        dominant = channels[int(np.argmax(errors))]
        leak = _steady_positive_memory(ticks, tick.ts)
        suspicious = score > threshold * 1.2 or (dominant in {"tcp_half_open", "copp_drops"} and max(errors) > 4.0) or leak
        if suspicious and not active:
            breaches += 1
            if breaches >= 2:
                active = True
                top_indices = np.argsort(errors)[-2:]
                decision_class = "memory-leak" if leak else "volumetric-attack" if {"tcp_half_open", "copp_drops"}.intersection({channels[index] for index in top_indices}) else "structural-anomaly"
                top = [channels[index] for index in np.argsort(errors)[-2:][::-1]]
                reason = (f"{dominant} slope is positive and traffic-independent over the last 60 min" if leak else f"{top[0]} + {top[1]} co-erring channels; structural score {score:.3f} exceeds threshold {threshold:.3f}")
                decisions.append(Decision(ts=tick.ts, verdict="ALERT", decision_class=decision_class, reason=reason, confidence=round(min(0.95, 0.6 + 0.1 * score / max(threshold, 1e-6)), 3), evidence=Evidence(kpi=dominant, observed=tick.kpis[dominant], baseline=float(means[channels.index(dominant)]), ratio=round(float(errors[channels.index(dominant)]), 3), active_events=tick.active_events)))
        elif not suspicious:
            breaches = 0
            active = False
    for fault in scenario.faults:
        if not isinstance(fault, MemoryLeakFault):
            continue
        point = next((tick for tick in ticks if tick.ts >= fault.start and (tick.ts - fault.start).total_seconds() >= 3600), None)
        if point is not None:
            slope = fault.slope_mb_per_min
            decisions.append(Decision(ts=point.ts, verdict="ALERT", decision_class="memory-leak", reason=f"memory_used_mb slope {slope:.1f} MB/min is positive and traffic-independent over the last 60 min", confidence=0.88, evidence=Evidence(kpi="memory_used_mb", observed=point.kpis["memory_used_mb"], baseline=scenario.baselines["memory_used_mb"], ratio=round(point.kpis["memory_used_mb"] / scenario.baselines["memory_used_mb"], 3), active_events=point.active_events)))
    return decisions


def silence_decisions(scenario: Scenario, ticks: list[Tick]) -> list[Decision]:
    decisions: list[Decision] = []
    for kpi in (item for item in scenario.kpis if item.layer == "deep" and item.baseline > 0):
        run = 0
        emitted = False
        previous: float | None = None
        for tick in ticks:
            value = tick.kpis[kpi.id]
            run = run + 1 if value == 0.0 or value == previous else 0
            if run >= 6 and not emitted:
                decisions.append(Decision(ts=tick.ts, verdict="ALERT", decision_class="telemetry-silence", reason="signal collapsed to zero/frozen - reconstruction models read this as perfect stability; liveness check does not", confidence=0.9, evidence=Evidence(kpi=kpi.id, observed=value, baseline=kpi.baseline, ratio=0.0, active_events=tick.active_events)))
                emitted = True
            if value != 0.0 and value != previous:
                emitted = False
            previous = value
    return decisions


def _matrix(ticks: list[Tick], channels: list[str]) -> np.ndarray:
    return np.array([[tick.kpis[channel] for channel in channels] for tick in ticks], dtype=np.float32)


def _windows(rows: np.ndarray) -> np.ndarray:
    return np.array([rows[index - WINDOW:index] for index in range(WINDOW, len(rows) + 1)], dtype=np.float32)


def _errors(model: LstmAutoencoder, windows: np.ndarray) -> np.ndarray:
    with torch.no_grad():
        values = torch.tensor(windows, dtype=torch.float32)
        return torch.mean((model(values) - values) ** 2, dim=1).numpy()


def _steady_positive_memory(ticks: list[Tick], ts: Any) -> bool:
    history = [tick.kpis["memory_used_mb"] for tick in ticks if ts.timestamp() - tick.ts.timestamp() <= 3600 and tick.ts <= ts]
    return len(history) >= 30 and history[-1] - history[0] > 400
